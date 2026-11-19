#!/usr/bin/env python3
"""Platform deploy tool: the single implementation behind the central GitHub workflows
and the local `make` targets, so CI and laptops run exactly the same steps.

  validate     check a developer values file against the chart contract
  render       print the manifests the chart would produce (for review / kubeconform)
  deploy       sync the service to an environment via Argo CD, gate on rollout health,
               roll back automatically on failure, record staging verifications
  promote      deploy to prod, only if the exact image tag was verified in staging
  decommission remove the service from an environment (staging before prod)

Environment facts (`global` values) come from Terraform: a YAML file locally
(local/generated/<env>-globals.yaml) or the SSM parameter /platform/<env>/chart-globals
in CI (--globals-ssm).
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHART = ROOT / "platform" / "charts" / "microservice"
ENVIRONMENTS = ("staging", "prod")
ANNOTATION_LAST_GOOD = "platform.example.com/last-good-release"


class PlatformError(RuntimeError):
    """A user-facing failure: printed without a traceback, exit code 1."""


def log(msg: str) -> None:
    print(f"[platform] {msg}", flush=True)


# ---- values ----------------------------------------------------------------------------
def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Helm-style merge: maps merge recursively, everything else (lists too) replaces."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError as exc:
        raise PlatformError(f"{path}: file not found") from exc
    except yaml.YAMLError as exc:
        raise PlatformError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PlatformError(f"{path}: top level must be a mapping")
    return data


def load_globals(env: str, globals_file: str | None, from_ssm: bool) -> dict[str, Any]:
    if from_ssm:
        import boto3  # CI only: credentials come from the GitHub OIDC deploy role

        param = boto3.client("ssm").get_parameter(Name=f"/platform/{env}/chart-globals")
        g = json.loads(param["Parameter"]["Value"])
    else:
        path = Path(globals_file or ROOT / "local" / "generated" / f"{env}-globals.yaml")
        if not path.exists():
            raise PlatformError(f"{path} not found: apply infra/terraform/envs/local first (make infra)")
        g = load_yaml(path).get("global", {})
    if g.get("environment") != env:
        raise PlatformError(f"globals are for {g.get('environment')!r}, expected {env!r}")
    return g


def validate_values(values_files: list[Path], chart: Path, globals_: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate developer values the way the deploy will use them.

    `values_files` are merged in order (the service's deploy/values-<env>.yaml first, then
    optional overlays). Returns the merged developer values. Raises PlatformError listing
    every violation with its JSON path, so a developer (or their agent) can fix them all
    in one pass.
    """
    dev: dict[str, Any] = {}
    for f in values_files:
        dev = deep_merge(dev, load_yaml(f))
    values_file = ", ".join(str(f) for f in values_files)
    errors: list[str] = []
    if "global" in dev:
        errors.append("global: is injected by the platform pipeline; remove it from your values file")
    image = dev.get("image", {})
    if isinstance(image, dict) and image.get("tag") not in (None, "replaced-by-pipeline"):
        errors.append("image.tag: leave as 'replaced-by-pipeline'; the pipeline sets the built git SHA")

    # The health contract must be declared by the service, not inherited from chart
    # defaults: it is a promise that the app really serves these endpoints.
    probes = dev.get("probes") if isinstance(dev.get("probes"), dict) else {}
    for probe in ("liveness", "readiness"):
        if not (isinstance(probes.get(probe), dict) and probes[probe].get("path")):
            errors.append(f"probes.{probe}.path: required; declare the endpoint your app serves")
    if not (isinstance(dev.get("metrics"), dict) and dev["metrics"].get("path")):
        errors.append("metrics.path: required; declare your Prometheus endpoint (e.g. /metrics)")

    placeholder_globals = globals_ or {
        "environment": "staging",
        "accountId": "000000000000",
        "region": "us-east-1",
        "clusterName": "validate",
        "oidcProviderArn": "arn:aws:iam::000000000000:oidc-provider/validate",
        "oidcIssuer": "validate",
    }
    merged = deep_merge(load_yaml(chart / "values.yaml"), {k: v for k, v in dev.items() if k != "global"})
    merged["global"] = deep_merge(merged.get("global", {}), placeholder_globals)
    merged.setdefault("image", {})["tag"] = "0000000"

    schema = json.loads((chart / "values.schema.json").read_text())
    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(merged), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {err.message}")

    aws = dev.get("aws") if isinstance(dev.get("aws"), dict) else {}
    for kind in ("dynamodb", "rds"):
        for item in aws.get(kind) or []:
            if (
                isinstance(item, dict)
                and item.get("deletionPolicy") == "delete"
                and item.get("deletionProtection", True) is not False
            ):
                errors.append(
                    f"aws.{kind}.{item.get('name')}: deletionPolicy: delete needs deletionProtection: false "
                    "(AWS would refuse the delete and decommission would hang)"
                )
    for kind, items in aws.items():
        seen = [i.get("name") for i in items if isinstance(i, dict)] if isinstance(items, list) else []
        dupes = {n for n in seen if seen.count(n) > 1}
        if dupes:
            errors.append(f"aws.{kind}: duplicate names {sorted(dupes)}")

    if errors:
        raise PlatformError(f"{values_file} is invalid:\n  - " + "\n  - ".join(errors))
    return dev


def deploy_values(dev: dict[str, Any], globals_: dict[str, Any], tag: str, release_id: str = "") -> dict[str, Any]:
    g = dict(globals_)
    if release_id:
        g["releaseId"] = release_id
    return deep_merge(dev, {"global": g, "image": {"tag": tag}})


def new_release_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        return f"gh-{run_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return "local-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")


# ---- process helpers -------------------------------------------------------------------
def run(cmd: list[str], *, input_: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, input=input_, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise PlatformError(f"{' '.join(cmd[:3])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def kubectl_json(*args: str) -> dict[str, Any] | None:
    proc = run(["kubectl", *args, "-o", "json"], check=False)
    if proc.returncode != 0:
        if "NotFound" in proc.stderr or "not found" in proc.stderr:
            return None
        raise PlatformError(f"kubectl {' '.join(args)}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def chart_version(chart: Path) -> str:
    return load_yaml(chart / "Chart.yaml")["version"]


def helm_render(values: dict[str, Any], chart: Path, namespace: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump(values, fh, sort_keys=False)
    try:
        return run(["helm", "template", values["service"]["name"], str(chart), "-n", namespace, "-f", fh.name]).stdout
    finally:
        os.unlink(fh.name)


# ---- Argo CD ---------------------------------------------------------------------------
def app_name(service: str, env: str) -> str:
    return f"{service}-{env}"


def build_application(values: dict[str, Any], env: str, chart_repo: str, version: str) -> dict[str, Any]:
    """The Argo CD Application the platform owns for one service in one environment.

    The chart comes from the platform registry at a pinned version; the values are the
    developer's file plus injected globals and the built image tag. (With a GitOps
    deploy repo, the same Application would reference the values file by git ref; the
    pipeline would commit the tag instead of applying it. See docs/design.md.)
    """
    service = values["service"]["name"]
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {
            "name": app_name(service, env),
            "namespace": "argocd",
            "labels": {
                "platform.example.com/service": service,
                "platform.example.com/environment": env,
                "platform.example.com/team": values["service"]["team"],
            },
            # Deleting the Application deletes everything it deployed (decommission).
            "finalizers": ["resources-finalizer.argocd.argoproj.io"],
        },
        "spec": {
            "project": env,
            "source": {
                "repoURL": chart_repo,
                "chart": "microservice",
                "targetRevision": version,
                "helm": {"releaseName": service, "valuesObject": values},
            },
            "destination": {"server": "https://kubernetes.default.svc", "namespace": f"{service}-{env}"},
            "syncPolicy": {
                "automated": {"prune": True, "selfHeal": True},
                "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"],
                "managedNamespaceMetadata": {
                    "labels": {"platform.example.com/environment": env, "platform.example.com/service": service}
                },
                "retry": {"limit": 10, "backoff": {"duration": "10s", "factor": 2, "maxDuration": "2m"}},
            },
        },
    }


def apply(obj: dict[str, Any]) -> None:
    run(
        ["kubectl", "apply", "--server-side", "--force-conflicts", "--field-manager=platform-deploy", "-f", "-"],
        input_=json.dumps(obj),
    )


# ---- promotion ledger (SSM in the staging account) -------------------------------------
def ssm_client(globals_: dict[str, Any]):
    import boto3

    if globals_.get("local"):
        # LocalStack: the 12-digit access key selects the environment's account.
        return boto3.client(
            "ssm",
            endpoint_url=os.environ.get("PLATFORM_AWS_ENDPOINT", "http://localhost:4566"),
            region_name=globals_["region"],
            aws_access_key_id=globals_["accountId"],
            aws_secret_access_key="test",
        )
    return boto3.client("ssm", region_name=globals_["region"])


def ledger_key(service: str, tag: str) -> str:
    return f"/platform/promotions/{service}/{tag}"


def record_verification(
    globals_: dict[str, Any], service: str, tag: str, values: dict[str, Any], chart_ver: str
) -> None:
    record = {
        "service": service,
        "tag": tag,
        "verifiedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": "staging",
        "chartVersion": chart_ver,
        "valuesSha256": hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(),
    }
    ssm_client(globals_).put_parameter(
        Name=ledger_key(service, tag), Value=json.dumps(record), Type="String", Overwrite=True
    )
    log(f"recorded staging verification {ledger_key(service, tag)}")


def read_verification(staging_globals: dict[str, Any], service: str, tag: str) -> dict[str, Any] | None:
    client = ssm_client(staging_globals)
    try:
        return json.loads(client.get_parameter(Name=ledger_key(service, tag))["Parameter"]["Value"])
    except client.exceptions.ParameterNotFound:
        return None


# ---- health gate -----------------------------------------------------------------------
def analysis_failure_summary(namespace: str) -> str:
    runs = kubectl_json("get", "analysisruns", "-n", namespace) or {"items": []}
    failed = [r for r in runs["items"] if r.get("status", {}).get("phase") in ("Failed", "Error")]
    if not failed:
        return ""
    latest = max(failed, key=lambda r: r["metadata"]["creationTimestamp"])
    parts = []
    for m in latest["status"].get("metricResults", []):
        if m.get("phase") in ("Failed", "Error"):
            last = (m.get("measurements") or [{}])[-1]
            parts.append(f"{m['name']}={m['phase']} (last value {last.get('value', 'n/a')})")
    return f"analysis {latest['metadata']['name']}: " + ", ".join(parts)


def rollout_hash(service: str, env: str) -> str | None:
    rollout = kubectl_json("get", "rollout", service, "-n", f"{service}-{env}")
    return (rollout or {}).get("status", {}).get("currentPodHash")


def safe_get(*args: str) -> dict[str, Any] | None:
    """kubectl get that tolerates transient API errors (logged; the caller retries)."""
    try:
        return kubectl_json(*args)
    except PlatformError as exc:
        log(f"transient: {exc}; retrying")
        return None


def wait_for_release(
    service: str, env: str, tag: str, previous_hash: str | None, timeout: int, *, rollback: bool = False
) -> tuple[bool, str]:
    """Block until the applied release is fully promoted (True) or aborted (False).

    Normal mode: every deploy stamps a unique release-id on the pod template, so a new
    release always has a new pod-template hash; we wait for the hash to move off
    `previous_hash` so the previous release's Healthy state is never mistaken for ours.
    Rollback mode: the target is a release that already ran, so we only wait for the
    Rollout to settle Healthy on `tag` (abort state left by the failed release is ignored).
    Healthy = Argo CD Synced + Healthy, the Deployment carries `tag`, and the Rollout has
    finished every step with stable ReplicaSet == current hash.
    """
    ns = f"{service}-{env}"
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        app = safe_get("get", "application", app_name(service, env), "-n", "argocd") or {}
        deploy = safe_get("get", "deployment", service, "-n", ns) or {}
        rollout = safe_get("get", "rollout", service, "-n", ns) or {}
        st = app.get("status", {})
        sync, health = st.get("sync", {}).get("status", "?"), st.get("health", {}).get("status", "?")
        containers = deploy.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or [{}]
        rs = rollout.get("status", {})
        phase, message = rs.get("phase", "Pending"), rs.get("message", "")
        steps = len(rollout.get("spec", {}).get("strategy", {}).get("canary", {}).get("steps", []))
        state = (
            f"argo sync={sync} health={health} | rollout phase={phase} "
            f"step={rs.get('currentStepIndex', '-')}/{steps} {message}"
        ).strip()
        if state != last:
            log(state)
            last = state
        on_tag = containers[0].get("image", "").endswith(f":{tag}")
        is_new = on_tag and (rollback or rs.get("currentPodHash") not in (None, previous_hash))
        if is_new and not rollback and (rs.get("abort") or phase == "Degraded"):
            return False, analysis_failure_summary(ns) or message or "rollout degraded"
        settled = phase == "Healthy" and rs.get("stableRS") == rs.get("currentPodHash") and not rs.get("abort")
        if is_new and settled and sync == "Synced" and health == "Healthy":
            return True, "release healthy"
        time.sleep(5)
    return False, f"timed out after {timeout}s ({last})"


def analysis_runs(namespace: str) -> list[dict[str, Any]]:
    return (safe_get("get", "analysisruns", "-n", namespace) or {"items": []})["items"]


def passed_analysis(namespace: str, pod_hash: str) -> bool:
    """A Successful AnalysisRun judged exactly this pod-template hash."""
    for run_ in analysis_runs(namespace):
        args = {x["name"]: x.get("value") for x in run_.get("spec", {}).get("args", [])}
        if args.get("canary-hash") == pod_hash and run_.get("status", {}).get("phase") == "Successful":
            return True
    return False


def run_verification_analysis(service: str, env: str, pod_hash: str, timeout: int) -> tuple[bool, str]:
    """Run the service's health AnalysisTemplate against `pod_hash` outside a canary.

    Argo Rollouts skips canary steps (and so analysis) on a Rollout's first revision. A
    release must never be recorded as verified without metrics having judged it, so the
    deploy CLI runs the same analysis itself in that case.
    """
    ns = f"{service}-{env}"
    template = kubectl_json("get", "analysistemplate", f"{service}-health", "-n", ns)
    if template is None:
        return False, "rollout.analysis is disabled; releases without analysis are not verifiable"
    name = f"{service}-verify-{pod_hash}-{int(time.time())}"
    apply(
        {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "AnalysisRun",
            "metadata": {"name": name, "namespace": ns, "labels": {"platform.example.com/verification": "true"}},
            "spec": {"args": [{"name": "canary-hash", "value": pod_hash}], "metrics": template["spec"]["metrics"]},
        }
    )
    log(f"no canary analysis ran for {pod_hash} (first revision): running verification analysis {name}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        phase = ((safe_get("get", "analysisrun", name, "-n", ns) or {}).get("status") or {}).get("phase")
        if phase == "Successful":
            return True, "verification analysis passed"
        if phase in ("Failed", "Error", "Inconclusive"):
            return False, analysis_failure_summary(ns) or f"verification analysis {phase}"
        time.sleep(5)
    return False, f"verification analysis timed out after {timeout}s"


def current_application(service: str, env: str) -> dict[str, Any] | None:
    return kubectl_json("get", "application", app_name(service, env), "-n", "argocd")


def mark_last_good(service: str, env: str, release_id: str) -> None:
    run(
        [
            "kubectl",
            "annotate",
            "application",
            app_name(service, env),
            "-n",
            "argocd",
            f"{ANNOTATION_LAST_GOOD}={release_id}",
            "--overwrite",
        ]
    )


def release_of(app: dict[str, Any] | None) -> str | None:
    return (
        (app or {})
        .get("spec", {})
        .get("source", {})
        .get("helm", {})
        .get("valuesObject", {})
        .get("global", {})
        .get("releaseId")
    )


def strip_server_fields(app: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(app)
    for k in ("status", "operation"):
        out.pop(k, None)
    out["metadata"] = {
        k: v for k, v in app["metadata"].items() if k in ("name", "namespace", "labels", "annotations", "finalizers")
    }
    return out


# ---- commands --------------------------------------------------------------------------
def cmd_validate(a: argparse.Namespace) -> None:
    validate_values([Path(v) for v in a.values], Path(a.chart))
    log(f"{', '.join(a.values)}: valid")


def cmd_render(a: argparse.Namespace) -> None:
    dev = validate_values([Path(v) for v in a.values], Path(a.chart))
    g = load_globals(a.env, a.globals, a.globals_ssm)
    values = deploy_values(dev, g, a.tag)
    sys.stdout.write(helm_render(values, Path(a.chart), f"{values['service']['name']}-{a.env}"))


def check_repository_owns(service: str) -> None:
    """In CI, a repo may only deploy the service it is named after (scaffold names repos
    after their service), so one team cannot overwrite another team's Application."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and repo.split("/", 1)[1] != service:
        raise PlatformError(f"service.name {service!r} does not match repository {repo!r}")


def do_deploy(a: argparse.Namespace, env: str) -> None:
    chart = Path(a.chart)
    dev = validate_values([Path(v) for v in a.values], chart)
    g = load_globals(env, a.globals, a.globals_ssm)
    release_id = new_release_id()
    values = deploy_values(dev, g, a.tag, release_id)
    service = values["service"]["name"]
    check_repository_owns(service)
    version = a.chart_version or chart_version(chart)
    helm_render(values, chart, f"{service}-{env}")  # fail fast on template errors
    log(f"deploying {service}:{a.tag} to {env} as release {release_id} (chart microservice {version})")

    previous = current_application(service, env)
    last_good = (previous or {}).get("metadata", {}).get("annotations", {}).get(ANNOTATION_LAST_GOOD)
    previous_hash = rollout_hash(service, env)
    apply(build_application(values, env, a.chart_repo, version))

    try:
        ok, reason = wait_for_release(service, env, a.tag, previous_hash, a.timeout)
        if ok:
            new_hash = rollout_hash(service, env) or ""
            if not passed_analysis(f"{service}-{env}", new_hash):
                ok, reason = run_verification_analysis(service, env, new_hash, a.timeout)
    except Exception as exc:  # any failure while judging the release still rolls back
        ok, reason = False, f"error while verifying the release: {exc}"

    if ok:
        mark_last_good(service, env, release_id)
        log(f"{service}:{a.tag} is healthy in {env} ({reason})")
        if env == "staging":
            record_verification(g, service, a.tag, values, version)
        return

    log(f"RELEASE FAILED: {reason}")
    if previous is not None and last_good and release_of(previous) == last_good:
        good_tag = previous["spec"]["source"]["helm"]["valuesObject"]["image"]["tag"]
        log(f"rolling back {service} in {env} to last good release {last_good} ({good_tag})")
        apply(strip_server_fields(previous))
        rb_ok, rb_reason = wait_for_release(service, env, good_tag, None, a.timeout, rollback=True)
        log(f"rollback {'complete' if rb_ok else 'FAILED: ' + rb_reason}; {service} runs {good_tag}")
    else:
        log("no previous healthy release to roll back to; leaving the failed release for inspection")
    raise PlatformError(f"deploy of {service}:{a.tag} to {env} failed: {reason}")


def cmd_deploy(a: argparse.Namespace) -> None:
    if a.env == "prod" and not a.i_am_the_promote_pipeline:
        raise PlatformError("prod deploys go through `promote` (requires a staging verification)")
    do_deploy(a, a.env)


def cmd_promote(a: argparse.Namespace) -> None:
    """Local/one-credential promotion: check the staging ledger, then deploy to prod."""
    dev = validate_values([Path(v) for v in a.values], Path(a.chart))
    staging_g = load_globals("staging", a.staging_globals, a.globals_ssm)
    require_verification(staging_g, dev["service"]["name"], a.tag, a.chart_version or chart_version(Path(a.chart)))
    do_deploy(a, "prod")


def require_verification(staging_g: dict[str, Any], service: str, tag: str, chart_ver: str) -> dict[str, Any]:
    check_repository_owns(service)
    record = read_verification(staging_g, service, tag)
    if record is None:
        raise PlatformError(
            f"{service}:{tag} has no staging verification ({ledger_key(service, tag)}). "
            "Deploy it to staging and let the rollout analysis pass first."
        )
    if record.get("chartVersion") != chart_ver:
        raise PlatformError(
            f"{service}:{tag} was verified in staging with chart {record.get('chartVersion')}, not {chart_ver}; "
            "redeploy it to staging with this chart version first"
        )
    log(f"staging verification found: verified {record['verifiedAt']} with chart {record['chartVersion']}")
    return record


def cmd_check_verified(a: argparse.Namespace) -> None:
    """CI step 1 of promotion, run with staging credentials (GitHub environment: staging)."""
    dev = validate_values([Path(v) for v in a.values], Path(a.chart))
    require_verification(
        load_globals("staging", a.globals, a.globals_ssm),
        dev["service"]["name"],
        a.tag,
        a.chart_version or chart_version(Path(a.chart)),
    )


def stuck_resources(namespace: str) -> list[str]:
    """Objects still terminating in `namespace`, with the controller's last error."""
    kinds = (
        "platformqueues,platformtopics,platformbuckets,platformtables,platformdatabases,"
        "platformworkloadidentities,queues.sqs.services.k8s.aws,topics.sns.services.k8s.aws,"
        "buckets.s3.services.k8s.aws,tables.dynamodb.services.k8s.aws,policies.iam.services.k8s.aws,"
        "roles.iam.services.k8s.aws"
    )
    data = kubectl_json("get", kinds, "-n", namespace) or {"items": []}
    out = []
    for obj in data["items"]:
        if not obj["metadata"].get("deletionTimestamp"):
            continue
        conds = obj.get("status", {}).get("conditions", [])
        rank = {"ACK.Terminal": 0, "ACK.Recoverable": 1, "Ready": 2}
        conds = sorted((c for c in conds if c.get("message")), key=lambda c: rank.get(c.get("type"), 9))
        msgs = [c["message"] for c in conds]
        out.append(f"{obj['kind']}/{obj['metadata']['name']}: {next((m for m in msgs if m), 'waiting')}")
    return out or ["(none found; check the Argo CD Application events)"]


DATA_KINDS = ("dynamodb", "s3", "rds")
PROTECTABLE = {"dynamodb": "deletionProtectionEnabled", "rds": "deletionProtection"}  # values kind -> ACK spec field


def release_data_stores(values: dict[str, Any]) -> list[str]:
    """Lift both guards on every data store: deletionPolicy -> delete, deletionProtection -> off."""
    released = []
    for kind in DATA_KINDS:
        for item in values.get("aws", {}).get(kind, []):
            item["deletionPolicy"] = "delete"
            if kind in PROTECTABLE:
                item["deletionProtection"] = False
            released.append(f"{kind}/{item['name']}")
    return released


def wait_for_data_release(namespace: str, timeout: int) -> None:
    """Block until AWS has applied the released guards on every ACK data store.

    The deletion-policy annotation must read `delete`, deletion protection must be off in
    the spec, and ACK must report the spec synced to AWS for that generation. Deleting
    earlier would leave ACK retrying a DeleteTable/DeleteDBInstance that AWS refuses.
    """
    kinds = "tables.dynamodb.services.k8s.aws,buckets.s3.services.k8s.aws,dbinstances.rds.services.k8s.aws"
    spec_field = {"Table": "deletionProtectionEnabled", "DBInstance": "deletionProtection"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = []
        for o in (safe_get("get", kinds, "-n", namespace) or {"items": []})["items"]:
            name, md = f"{o['kind']}/{o['metadata']['name']}", o["metadata"]
            if md.get("annotations", {}).get("services.k8s.aws/deletion-policy") != "delete":
                pending.append(f"{name} (deletion-policy)")
            elif o["kind"] in spec_field:
                if o.get("spec", {}).get(spec_field[o["kind"]]) is not False:
                    pending.append(f"{name} (deletion protection)")
                elif not any(
                    c.get("type") == "ACK.ResourceSynced"
                    and c.get("status") == "True"
                    and c.get("observedGeneration", md.get("generation")) == md.get("generation")
                    for c in o.get("status", {}).get("conditions", [])
                ):
                    pending.append(f"{name} (protection change not yet applied in AWS)")
        if not pending:
            return
        log(f"waiting before deletion: {pending}")
        time.sleep(5)
    raise PlatformError(
        f"data stores in {namespace} were not released within {timeout}s: {pending}. "
        "Nothing was deleted; fix the cause and re-run."
    )


def cmd_decommission(a: argparse.Namespace) -> None:
    service, env = a.service, a.env
    # Single-cluster (local) guard. In CI the ordering is enforced by job dependencies
    # (decommission.yaml: prod needs staging), since each environment is its own cluster.
    if env == "prod" and not a.force:
        staging = current_application(service, "staging")
        if staging is not None:
            raise PlatformError(f"decommission {service} from staging first (its Application still exists)")
    app = current_application(service, env)
    if app is None:
        log(f"{app_name(service, env)} not found; nothing to do")
        return
    values = app["spec"]["source"]["helm"]["valuesObject"]
    retained = [
        f"{kind}/{item['name']}"
        for kind in ("dynamodb", "s3", "rds")
        for item in values.get("aws", {}).get(kind, [])
        if item.get("deletionPolicy", "retain") == "retain"
    ]
    if a.delete_data and any(values.get("aws", {}).get(k) for k in DATA_KINDS):
        released = release_data_stores(values)
        log(f"--delete-data: lifting deletionPolicy=retain and deletion protection on {released}")
        app["spec"]["source"]["helm"]["valuesObject"] = values
        apply(strip_server_fields(app))
        wait_for_data_release(f"{service}-{env}", a.timeout)
        retained = []

    log(f"deleting Application {app_name(service, env)} (cascades to every resource it created)")
    proc = run(
        [
            "kubectl",
            "delete",
            "application",
            app_name(service, env),
            "-n",
            "argocd",
            "--wait=true",
            f"--timeout={a.timeout}s",
        ],
        check=False,
    )
    if proc.returncode != 0:
        stuck = stuck_resources(f"{service}-{env}")
        raise PlatformError(
            f"{app_name(service, env)} did not finish deleting within {a.timeout}s. Resources still "
            "terminating (fix the cause, then re-run; deletion resumes automatically):\n  - " + "\n  - ".join(stuck)
        )
    run(
        [
            "kubectl",
            "delete",
            "namespace",
            f"{service}-{env}",
            "--ignore-not-found",
            "--wait=true",
            f"--timeout={a.timeout}s",
        ]
    )
    if env == "staging":
        log("staging verification records are kept as the audit trail of what was promoted")
    if retained:
        log("RETAINED in AWS (deletionPolicy=retain), delete or archive deliberately: " + ", ".join(retained))
    log(f"{service} decommissioned from {env}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="platform_deploy", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser, *, env: bool = True, tag: bool = True) -> None:
        sp.add_argument(
            "--values",
            required=True,
            action="append",
            help="developer values file (deploy/values-<env>.yaml); repeat to add overlays",
        )
        sp.add_argument("--chart", default=str(DEFAULT_CHART), help="path to the microservice chart")
        if env:
            sp.add_argument("--env", required=True, choices=ENVIRONMENTS)
        if tag:
            sp.add_argument("--tag", required=True, help="image tag built by CI (the git SHA)")
        sp.add_argument("--globals", help="globals YAML (default local/generated/<env>-globals.yaml)")
        sp.add_argument("--globals-ssm", action="store_true", help="read globals from SSM (CI)")

    def delivery(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--chart-repo", default=os.environ.get("PLATFORM_CHART_REPO", "kind-registry:5000/charts"))
        sp.add_argument("--chart-version", help="published chart version (default: Chart.yaml)")
        sp.add_argument("--timeout", type=int, default=900, help="seconds to wait for a healthy release")

    sp = sub.add_parser("validate", help=cmd_validate.__doc__)
    common(sp, env=False, tag=False)
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("render")
    common(sp)
    sp.set_defaults(fn=cmd_render)

    sp = sub.add_parser("deploy")
    common(sp)
    delivery(sp)
    sp.add_argument("--i-am-the-promote-pipeline", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(fn=cmd_deploy)

    sp = sub.add_parser("promote", help="deploy a staging-verified tag to prod")
    common(sp, env=False)
    delivery(sp)
    sp.add_argument("--staging-globals", help="staging globals YAML (to read the verification ledger)")
    sp.set_defaults(fn=cmd_promote)

    sp = sub.add_parser("check-verified", help="fail unless the tag passed staging (promotion step 1)")
    common(sp, env=False)
    sp.add_argument("--chart-version", help="chart version prod will deploy (default: Chart.yaml)")
    sp.set_defaults(fn=cmd_check_verified)

    sp = sub.add_parser("decommission")
    sp.add_argument("--service", required=True)
    sp.add_argument("--env", required=True, choices=ENVIRONMENTS)
    sp.add_argument("--delete-data", action="store_true", help="also delete retained data stores")
    sp.add_argument("--force", action="store_true", help="allow prod before staging (break-glass)")
    sp.add_argument("--timeout", type=int, default=600)
    sp.set_defaults(fn=cmd_decommission)

    a = p.parse_args(argv)
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:  # validate/render do not need boto3
        BotoCoreError = ClientError = PlatformError  # noqa: N806
    try:
        a.fn(a)
    except PlatformError as exc:
        print(f"[platform] ERROR: {exc}", file=sys.stderr)
        return 1
    except (BotoCoreError, ClientError) as exc:
        print(f"[platform] ERROR: AWS call failed: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"[platform] ERROR: required tool or file not found: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[platform] ERROR: malformed JSON from a platform record or kubectl: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
