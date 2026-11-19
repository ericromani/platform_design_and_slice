"""Every preset scaffolds cleanly and its deploy values satisfy the chart contract."""

from __future__ import annotations

import argparse
from pathlib import Path

import new_service
import platform_deploy as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "platform" / "charts" / "microservice"
KEYS = list(
    new_service.placeholders(argparse.Namespace(name="x", team="t", description="d", org="o", image_registry=""))
)


@pytest.mark.parametrize("language", sorted(new_service.PRESETS))
def test_preset_scaffolds_without_placeholders(tmp_path, language):
    dest = tmp_path / f"svc-{language}"
    rc = new_service.main(
        [
            "--name",
            f"svc-{language}",
            "--team",
            "platform",
            "--language",
            language,
            "--description",
            "test service",
            "--dest",
            str(dest),
        ]
    )
    assert rc == 0
    for f in dest.rglob("*"):
        assert "__SERVICE_NAME__" not in str(f) and "__JAVA_PACKAGE_PATH__" not in str(f)
        if f.is_file() and f.suffix not in {".jar"}:
            text = f.read_text(errors="ignore")
            assert not [k for k in KEYS if k in text], f
    for env in ("staging", "prod"):
        dev = pd.validate_values([dest / "deploy" / f"values-{env}.yaml"], CHART)
        assert dev["service"]["name"] == f"svc-{language}"
    for wf in ("ci.yaml", "deploy.yaml", "decommission.yaml"):
        assert (dest / ".github" / "workflows" / wf).exists()
    assert (dest / "CLAUDE.md").exists()


@pytest.mark.parametrize("bad", ["Orders", "1svc", "svc_", "a" * 33])
def test_rejects_invalid_names(tmp_path, bad):
    with pytest.raises(SystemExit):
        new_service.main(["--name", bad, "--team", "platform", "--language", "python", "--dest", str(tmp_path / "x")])
