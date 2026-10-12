import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate data + permissions before importing app modules.
_tmp = Path(tempfile.mkdtemp(prefix="jarvis-test-"))
os.environ["JARVIS_DATA_DIR"] = str(_tmp / "data")
os.environ["JARVIS_PERMISSIONS_FILE"] = str(_tmp / "permissions.json")
os.environ["JARVIS_AGENT_TOKEN"] = "test-token-123456"
os.environ.pop("ANTHROPIC_API_KEY", None)
APPROVED = _tmp / "approved"
(APPROVED / "notes").mkdir(parents=True)
(APPROVED / "notes" / "plan.md").write_text("# Plan\nShip JARVIS.")
(APPROVED / ".env").write_text("SECRET=1")
(_tmp / "outside.txt").write_text("private")
(_tmp / "permissions.json").write_text(json.dumps({
    "approved_apps": ["Safari"], "approved_domains": ["example.com"],
    "approved_directories": [str(APPROVED)], "approval_required": ["read_text_file"], "disabled_tools": []}))

import pytest  # noqa: E402


@pytest.fixture
def tmp_root():
    return _tmp


@pytest.fixture
def approved_dir():
    return APPROVED
