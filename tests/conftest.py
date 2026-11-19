import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform" / "workflows" / "scripts"))
sys.path.insert(0, str(ROOT / "scaffold"))


@pytest.fixture(autouse=True)
def _no_ambient_ci_env(monkeypatch):
    """Tests must not inherit the CI runner's GITHUB_* variables: the deploy CLI changes
    behaviour when they are set (repo ownership check, release ids). Tests that exercise
    that behaviour set them explicitly."""
    for var in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_ACTIONS"):
        monkeypatch.delenv(var, raising=False)
