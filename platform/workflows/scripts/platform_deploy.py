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


def wait_for_release(service: str, env: str, tag: str, previous_hash: str | None, timeout: int) -> tuple[bool, str]:
    """Block until the newly applied release is fully promoted (True) or aborted (False).

    Every deploy stamps a unique release-id on the pod template, so a new release always
    has a new pod-template hash; waiting for the hash to move off `previous_hash` stops
    us from mistaking the previous release's Healthy state for the new one's.
    Healthy means: Argo CD synced, the Deployment carries `tag`, and the Rollout finished
    every canary step with passing analysis (stable ReplicaSet == current hash).
    """
    ns = f"{service}-{env}"
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        app = kubectl_json("get", "application", app_name(service, env), "-n", "argocd") or {}
        st = app.get("status", {})
        sync, health = st.get("sync", {}).get("status", "?"), st.get("health", {}).get("status", "?")
        deploy = kubectl_json("get", "deployment", service, "-n", ns) or {}
        rollout = kubectl_json("get", "rollout", service, "-n", ns) or {}
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
        is_new = containers[0].get("image", "").endswith(f":{tag}") and rs.get("currentPodHash") not in (
            None,
            previous_hash,
        )
        if is_new and (rs.get("abort") or phase == "Degraded"):
            return False, analysis_failure_summary(ns) or message or "rollout degraded"
        if is_new and phase == "Healthy" and rs.get("stableRS") == rs.get("currentPodHash") and sync == "Synced":
            return True, "release healthy"
        time.sleep(5)
    return False, f"timed out after {timeout}s ({last})"


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


def do_deploy(a: argparse.Namespace, env: str) -> None:
    chart = Path(a.chart)
    dev = validate_values([Path(v) for v in a.values], chart)
    g = load_globals(env, a.globals, a.globals_ssm)
    release_id = new_release_id()
    values = deploy_values(dev, g, a.tag, release_id)
    service = values["service"]["name"]
    version = a.chart_version or chart_version(chart)
    helm_render(values, chart, f"{service}-{env}")  # fail fast on template errors
    log(f"deploying {service}:{a.tag} to {env} as release {release_id} (chart microservice {version})")

    previous = current_application(service, env)
    last_good = (previous or {}).get("metadata", {}).get("annotations", {}).get(ANNOTATION_LAST_GOOD)
    previous_hash = rollout_hash(service, env)
    apply(build_application(values, env, a.chart_repo, version))

    ok, reason = wait_for_release(service, env, a.tag, previous_hash, a.timeout)
    if ok:
        mark_last_good(service, env, release_id)
        log(f"{service}:{a.tag} is healthy in {env}")
        if env == "staging":
            record_verification(g, service, a.tag, values, version)
        return

    log(f"RELEASE FAILED: {reason}")
    if previous is not None and last_good and release_of(previous) == last_good:
        good_tag = previous["spec"]["source"]["helm"]["valuesObject"]["image"]["tag"]
        log(f"rolling back {service} in {env} to last good release {last_good} ({good_tag})")
        failed_hash = rollout_hash(service, env)
        apply(strip_server_fields(previous))
        rb_ok, rb_reason = wait_for_release(service, env, good_tag, failed_hash, a.timeout)
        log(f"rollback {'complete' if rb_ok else 'FAILED: ' + rb_reason}; {service} runs {good_tag}")
    else:
        log("no previous healthy release to roll back to; leaving the failed release for inspection")
    raise PlatformError(f"deploy of {service}:{a.tag} to {env} failed: {reason}")


def cmd_deploy(a: argparse.Namespace) -> None:
    if a.env == "prod" and not a.i_am_the_promote_pipeline:
        raise PlatformError("prod deploys go through `promote` (requires a staging verification)")
    do_deploy(a, a.env)


def cmd_promote(a: argparse.Namespace) -> None:
    dev = validate_values([Path(v) for v in a.values], Path(a.chart))
    service = dev["service"]["name"]
    staging_g = load_globals("staging", a.staging_globals, a.globals_ssm)
    record = read_verification(staging_g, service, a.tag)
    if record is None:
        raise PlatformError(
            f"{service}:{a.tag} has no staging verification ({ledger_key(service, a.tag)}). "
            "Deploy it to staging and let the rollout analysis pass first."
        )
    log(f"staging verification found: verified {record['verifiedAt']} with chart {record['chartVersion']}")
    do_deploy(a, "prod")


def cmd_decommission(a: argparse.Namespace) -> None:
    service, env = a.service, a.env
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
    if a.delete_data and retained:
        log(f"--delete-data: switching {retained} to deletionPolicy=delete before removal")
        for kind in ("dynamodb", "s3", "rds"):
            for item in values.get("aws", {}).get(kind, []):
                item["deletionPolicy"] = "delete"
        app["spec"]["source"]["helm"]["valuesObject"] = values
        apply(strip_server_fields(app))
        time.sleep(20)  # let Argo CD + kro propagate the new annotation to ACK
        retained = []

    log(f"deleting Application {app_name(service, env)} (cascades to every resource it created)")
    run(
        [
            "kubectl",
            "delete",
            "application",
            app_name(service, env),
            "-n",
            "argocd",
            "--wait=true",
            f"--timeout={a.timeout}s",
        ]
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

    sp = sub.add_parser("decommission")
    sp.add_argument("--service", required=True)
    sp.add_argument("--env", required=True, choices=ENVIRONMENTS)
    sp.add_argument("--delete-data", action="store_true", help="also delete retained data stores")
    sp.add_argument("--force", action="store_true", help="allow prod before staging (break-glass)")
    sp.add_argument("--timeout", type=int, default=600)
    sp.set_defaults(fn=cmd_decommission)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except PlatformError as exc:
        print(f"[platform] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
