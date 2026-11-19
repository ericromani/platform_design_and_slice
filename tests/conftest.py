import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform" / "workflows" / "scripts"))
sys.path.insert(0, str(ROOT / "scaffold"))
