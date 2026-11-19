"""Unit tests for the deploy tool's pure logic (no cluster needed)."""

from __future__ import annotations

from pathlib import Path

import platform_deploy as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "platform" / "charts" / "microservice"
EXAMPLE = ROOT / "examples" / "orders-service" / "deploy"
GLOBALS = {
    "environment": "staging",
    "accountId": "111111111111",
    "region": "us-east-1",
    "clusterName": "c",
    "oidcProviderArn": "arn:aws:iam::111111111111:oidc-provider/x",
    "oidcIssuer": "x",
}


def write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "values.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def example() -> dict:
    return yaml.safe_load((EXAMPLE / "values-staging.yaml").read_text())


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_example_values_are_valid(env):
    dev = pd.validate_values([EXAMPLE / f"values-{env}.yaml"], CHART)
    assert dev["service"]["name"] == "orders-service"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda v: v.__setitem__("global", {"environment": "prod"}), "global: is injected"),
        (lambda v: v["probes"].pop("readiness"), "probes.readiness.path: required"),
        (lambda v: v.pop("metrics"), "metrics.path: required"),
        (lambda v: v["image"].__setitem__("tag", "latest"), "image.tag: leave as"),
        (lambda v: v["aws"]["sqs"].append({"name": "orders", "access": "publish"}), "duplicate names"),
        (lambda v: v["aws"]["sqs"][0].__setitem__("access", "admin"), "aws.sqs.0.access"),
        (lambda v: v["env"].__setitem__("AWS_SECRET_ACCESS_KEY", "x"), "env"),
        (lambda v: v["service"].__setitem__("name", "Orders_Service"), "service.name"),
        (lambda v: v.__setitem__("unknownKey", 1), "Additional properties are not allowed"),
    ],
)
def test_invalid_values_are_reported(tmp_path, mutate, message):
    values = example()
    mutate(values)
    with pytest.raises(pd.PlatformError, match=message):
        pd.validate_values([write(tmp_path, values)], CHART)


def test_overlays_merge_in_order(tmp_path):
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("env:\n  FAIL_RATE: '1'\n")
    dev = pd.validate_values([EXAMPLE / "values-staging.yaml", overlay], CHART)
    assert dev["env"] == {"LOG_LEVEL": "INFO", "POLL_WAIT_SECONDS": 5, "FAIL_RATE": "1"}


def test_deep_merge_replaces_lists_and_merges_maps():
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    out = pd.deep_merge(base, {"a": {"c": [3]}, "e": 2})
    assert out == {"a": {"b": 1, "c": [3]}, "d": 1, "e": 2}
    assert base["a"]["c"] == [1, 2]  # input untouched


def test_deploy_values_inject_globals_tag_and_release():
    values = pd.deploy_values(example(), GLOBALS, "abc1234", "rel-1")
    assert values["image"]["tag"] == "abc1234"
    assert values["global"]["releaseId"] == "rel-1"
    assert values["global"]["accountId"] == "111111111111"


def test_application_targets_env_project_and_namespace():
    values = pd.deploy_values(example(), GLOBALS, "abc1234", "rel-1")
    app = pd.build_application(values, "staging", "registry/charts", "0.1.0")
    assert app["metadata"]["name"] == "orders-service-staging"
    assert app["spec"]["project"] == "staging"
    assert app["spec"]["destination"]["namespace"] == "orders-service-staging"
    assert app["spec"]["source"]["targetRevision"] == "0.1.0"
    assert "resources-finalizer.argocd.argoproj.io" in app["metadata"]["finalizers"]
    assert app["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True}


def test_prod_deploy_requires_promote(monkeypatch, capsys):
    rc = pd.main(["deploy", "--env", "prod", "--tag", "abc", "--values", str(EXAMPLE / "values-prod.yaml")])
    assert rc == 1
    assert "prod deploys go through `promote`" in capsys.readouterr().err


def test_release_ids_are_unique_per_github_run(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert pd.new_release_id() == "gh-42-2"


def test_strip_server_fields_keeps_only_reapplyable_metadata():
    app = {
        "metadata": {"name": "a", "namespace": "argocd", "uid": "u", "resourceVersion": "1", "annotations": {"k": "v"}},
        "spec": {},
        "status": {"x": 1},
        "operation": {},
    }
    out = pd.strip_server_fields(app)
    assert out == {"metadata": {"name": "a", "namespace": "argocd", "annotations": {"k": "v"}}, "spec": {}}
