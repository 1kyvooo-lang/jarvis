import os

import pytest
from fastapi.testclient import TestClient

from agent.registry import ToolError, registry
from agent.safety import check_url, resolve_inside_roots
from agent.server import app
from shared.settings import load_permissions

H = {"Authorization": "Bearer test-token-123456"}


@pytest.fixture
def client():
    return TestClient(app)


def test_auth_required(client):
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/status", headers=H).json()["ok"]
    assert client.get("/health").json() == {"ok": True}


def test_get_datetime(client):
    r = client.post("/execute", headers=H, json={"request_id": "req-00000001", "tool": "get_datetime", "args": {}}).json()
    assert r["ok"] and "iso" in r["output"]


def test_schema_validation(client):
    r = client.post("/execute", headers=H, json={"request_id": "req-00000002", "tool": "get_datetime", "args": {"x": 1}}).json()
    assert not r["ok"] and "Invalid arguments" in r["error"]
    r = client.post("/execute", headers=H, json={"request_id": "req-00000003", "tool": "rm_rf", "args": {}}).json()
    assert not r["ok"] and "Unknown tool" in r["error"]


def test_no_shell_tool_exists():
    assert not any(n for n in registry.tools if "shell" in n or "exec" in n or "command" in n)


def test_path_traversal_blocked(approved_dir, tmp_root):
    perms = load_permissions()
    with pytest.raises(ToolError):
        resolve_inside_roots(str(approved_dir / ".." / "outside.txt"), perms)
    with pytest.raises(ToolError):
        resolve_inside_roots("/etc/passwd", perms)
    with pytest.raises(ToolError):
        resolve_inside_roots(str(approved_dir / ".env"), perms)
    link = approved_dir / "sneaky.txt"
    if not link.exists():
        os.symlink(tmp_root / "outside.txt", link)
    with pytest.raises(ToolError):
        resolve_inside_roots(str(link), perms)
    assert resolve_inside_roots(str(approved_dir / "notes" / "plan.md"), perms).name == "plan.md"


def test_url_allowlist():
    perms = load_permissions()
    assert check_url("https://www.example.com/a", perms)
    for bad in ["https://evil.com", "https://example.com.evil.com", "file:///etc/passwd",
                "javascript:alert(1)", "https://user:pw@example.com"]:
        with pytest.raises(ToolError):
            check_url(bad, perms)


def test_approval_enforced_by_agent(client, approved_dir):
    path = str(approved_dir / "notes" / "plan.md")
    r = client.post("/execute", headers=H, json={"request_id": "req-00000010", "tool": "read_text_file", "args": {"path": path}}).json()
    assert not r["ok"] and "approval" in r["error"]
    r = client.post("/execute", headers=H, json={"request_id": "req-00000011", "tool": "read_text_file",
                                                 "args": {"path": path}, "approved": True}).json()
    assert r["ok"] and "Ship JARVIS" in r["output"]["content"]


def test_open_app_allowlist(client):
    r = client.post("/execute", headers=H, json={"request_id": "req-00000020", "tool": "open_app",
                                                 "args": {"name": "Terminal"}, "approved": True}).json()
    assert not r["ok"] and "not in the approved list" in r["error"]


def test_search_files(client):
    r = client.post("/execute", headers=H, json={"request_id": "req-00000030", "tool": "search_files", "args": {"query": "plan"}}).json()
    assert r["ok"] and any(x["path"].endswith("plan.md") for x in r["output"]["results"])
    assert not any(x["path"].endswith(".env") for x in r["output"]["results"])


def test_idempotent_and_emergency_stop(client):
    body = {"request_id": "req-00000040", "tool": "get_datetime", "args": {}}
    a = client.post("/execute", headers=H, json=body).json()
    b = client.post("/execute", headers=H, json=body).json()
    assert b.get("duplicate") and a["output"] == b["output"]
    client.post("/control/stop", headers=H)
    r = client.post("/execute", headers=H, json={"request_id": "req-00000041", "tool": "get_datetime", "args": {}}).json()
    assert not r["ok"] and "Emergency stop" in r["error"]
    client.post("/control/resume", headers=H)
