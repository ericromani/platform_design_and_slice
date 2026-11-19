"""Every YAML snippet in the new-service cookbook must validate against the chart.

The skill tells agents to copy these; a stale snippet would teach them invalid values.
"""

from __future__ import annotations

import re
from pathlib import Path

import platform_deploy as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "platform" / "charts" / "microservice"
COOKBOOK = ROOT / ".claude" / "skills" / "new-service" / "references" / "values-cookbook.md"
HEADER = {
    "service": {"name": "cookbook-svc", "team": "platform"},
    "image": {"repository": "localhost:5001/cookbook-svc", "tag": "replaced-by-pipeline"},
    "probes": {"liveness": {"path": "/healthz"}, "readiness": {"path": "/readyz"}},
    "metrics": {"path": "/metrics"},
}
SNIPPETS = re.findall(r"```yaml\n(.*?)```", COOKBOOK.read_text(), re.S)


def test_cookbook_has_snippets():
    assert len(SNIPPETS) >= 6


@pytest.mark.parametrize("snippet", SNIPPETS, ids=[s.splitlines()[0][:40] for s in SNIPPETS])
def test_snippet_validates(tmp_path, snippet):
    values = pd.deep_merge(HEADER, yaml.safe_load(snippet))
    # The load-balancer snippet needs a cert only when internet-facing; schema allows "".
    f = tmp_path / "values.yaml"
    f.write_text(yaml.safe_dump(values))
    pd.validate_values([f], CHART)
