"""Backend ↔ agent flows (in-process), with a scripted stand-in for Hermes."""
import json
import os
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
os.environ["JARVIS_APPROVAL_WAIT"] = "6"

from agent.server import app as agent_app  # noqa: E402
from backend import agent_client, db, main  # noqa: E402
from shared.settings import agent_token  # noqa: E402

INTERNAL = {"Authorization": f"Bearer {agent_token()}"}


class FakeBrain:
    """Replays scripted turns of normalized Hermes events."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def stream(self, *, conversation, text, instructions, **kw):
        self.calls.append({"conversation": conversation, "text": text, "instructions": instructions})
        for ev in self.turns.pop(0):
            yield ev


def events(resp):
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def client():
    agent_client._transport = httpx.ASGITransport(app=agent_app)
    with TestClient(main.app) as c:
        yield c
    main.brain_override = None


def test_chat_streams_tools_and_persists(client):
    main.brain_override = FakeBrain([[
        {"type": "text", "delta": "Checking. "},
        {"type": "tool_start", "id": "c1", "name": "system_status", "input": {}},
        {"type": "tool_result", "id": "c1", "name": "system_status", "status": "ok", "output": "{\"cpu\": 3}"},
        {"type": "text", "delta": "All good."},
        {"type": "done"},
    ]])
    evs = events(client.post("/api/chat", json={"message": "How's my Mac?"}))
    types = [e["type"] for e in evs]
    assert types[0] == "conversation" and "tool_start" in types and types[-1] == "done"
    cid = evs[0]["id"]
    assert main.brain_override.calls[0]["conversation"] == f"jarvis-{cid}"
    conv = client.get(f"/api/conversations/{cid}").json()
    a = conv["messages"][1]
    assert a["role"] == "assistant" and a["text"] == "Checking. All good."
    assert a["tools"][0]["name"] == "system_status" and a["tools"][0]["status"] == "ok"


def test_brain_error_is_shown_and_saved(client):
    main.brain_override = FakeBrain([[{"type": "error", "message": "No model configured"}]])
    evs = events(client.post("/api/chat", json={"message": "hi"}))
    assert evs[-1]["type"] == "error" and "No model" in evs[-1]["message"]
    conv = client.get(f"/api/conversations/{evs[0]['id']}").json()
    assert "No model" in conv["messages"][-1]["error"]


def test_memory_goes_into_instructions(client):
    client.post("/api/memories", json={"kind": "preference", "content": "Prefers concise answers"})
    assert client.post("/api/memories", json={"kind": "fact", "content": "my password is hunter22"}).status_code == 400
    main.brain_override = FakeBrain([[{"type": "text", "delta": "ok"}, {"type": "done"}]])
    events(client.post("/api/chat", json={"message": "hello"}))
    assert "Prefers concise answers" in main.brain_override.calls[0]["instructions"]


def test_internal_requires_token(client):
    assert client.get("/api/internal/tools").status_code == 401
    tools = client.get("/api/internal/tools", headers=INTERNAL).json()["tools"]
    names = {t["name"] for t in tools}
    assert {"system_status", "save_memory", "open_app"} <= names
    assert not any("shell" in n or "terminal" in n for n in names)


def test_internal_run_auto_tool(client):
    r = client.post("/api/internal/run", headers=INTERNAL, json={"tool": "get_datetime", "args": {}}).json()
    assert r["status"] == "ok" and "iso" in r["output"]


def _later(fn, delay=0.8):
    t = threading.Thread(target=lambda: (time.sleep(delay), fn()))
    t.start()
    return t


def test_internal_run_blocks_until_approved(client, approved_dir):
    path = str(approved_dir / "notes" / "plan.md")

    def approve():
        pending = client.get("/api/approvals").json()
        client.post(f"/api/approvals/{pending[0]['id']}/approve")
    t = _later(approve)
    r = client.post("/api/internal/run", headers=INTERNAL, json={"tool": "read_text_file", "args": {"path": path}}).json()
    t.join()
    assert r["status"] == "ok" and "Ship JARVIS" in r["output"]["content"]


def test_internal_run_denied(client, approved_dir):
    path = str(approved_dir / "notes" / "plan.md")
    t = _later(lambda: client.post(f"/api/approvals/{client.get('/api/approvals').json()[0]['id']}/deny"))
    r = client.post("/api/internal/run", headers=INTERNAL, json={"tool": "read_text_file", "args": {"path": path}}).json()
    t.join()
    assert r["status"] == "error" and "denied" in r["error"]


def test_browser_authorize_flow(client):
    ok = client.post("/api/internal/authorize", headers=INTERNAL,
                     json={"tool": "browser_snapshot", "args": {}, "page_url": "https://evil.org"}).json()
    assert ok["decision"] == "allow"
    no = client.post("/api/internal/authorize", headers=INTERNAL,
                     json={"tool": "browser_navigate", "args": {"url": "file:///etc/passwd"}}).json()
    assert no["decision"] == "deny"
    t = _later(lambda: client.post(f"/api/approvals/{client.get('/api/approvals').json()[0]['id']}/approve"))
    r = client.post("/api/internal/authorize", headers=INTERNAL,
                    json={"tool": "browser_click", "args": {"element": "Place order button"},
                          "page_url": "https://example.com/cart"}).json()
    t.join()
    assert r["decision"] == "allow" and r["approval_id"]
    client.post("/api/internal/report", headers=INTERNAL,
                json={"tool": "browser_click", "args": {}, "ok": True, "summary": "clicked", "approval_id": r["approval_id"]})
    assert client.get("/api/approvals?status=all").json()[0]["status"] == "executed"


def test_approval_expires(client):
    os.environ["JARVIS_APPROVAL_WAIT"] = "6"
    r = client.post("/api/internal/authorize", headers=INTERNAL,
                    json={"tool": "browser_fill_form", "args": {"fields": []}, "page_url": "https://example.com"}).json()
    assert r["decision"] == "deny" and "within" in r["reason"]


def test_emergency_stop_blocks_everything(client):
    client.post("/api/emergency-stop")
    assert client.post("/api/internal/run", headers=INTERNAL, json={"tool": "get_datetime"}).json()["status"] == "error"
    assert client.post("/api/internal/authorize", headers=INTERNAL,
                       json={"tool": "browser_snapshot", "args": {}}).json()["decision"] == "deny"
    client.post("/api/resume")
    assert client.post("/api/internal/run", headers=INTERNAL, json={"tool": "get_datetime"}).json()["status"] == "ok"


def test_automation_proposal_and_scheduler(client):
    import asyncio
    from backend import scheduler
    r = client.post("/api/internal/run", headers=INTERNAL, json={"tool": "propose_automation", "args": {
        "title": "Status check", "steps": [{"tool": "system_status", "args": {}}]}}).json()
    assert r["status"] == "ok"
    tid = r["output"]["task_id"]
    asyncio.run(scheduler.tick())
    assert db.one("SELECT status FROM tasks WHERE id=?", (tid,))["status"] == "proposed"
    assert client.post(f"/api/tasks/{tid}/approve").json()["ok"]
    asyncio.run(scheduler.tick())
    assert db.one("SELECT status FROM tasks WHERE id=?", (tid,))["status"] == "completed"


def test_voice_without_key(client):
    r = client.post("/api/voice/tts", json={"text": "hello"})
    assert r.status_code == 412 and "ElevenLabs" in r.json()["detail"]
