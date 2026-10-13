"""JARVIS backend API. Run: python -m backend.main"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shared.settings import (BACKEND_HOST, BACKEND_PORT, DATA_DIR, LOG_DIR, ROOT, agent_token, load_permissions,
                             save_permissions)

from . import (actions, agent_client, browser_policy, chat, db, hermes, integrations, memory, phone, scheduler,
               secrets_store, services, updater, voice, wake)
from . import google, public, routines

log = logging.getLogger("jarvis.backend")


def html_escape(v: str) -> str:
    import html as _h
    return _h.escape(v)
brain_override = None  # tests inject a fake brain here


def get_brain():
    if brain_override is not None:
        return brain_override
    return hermes.HermesClient(key=hermes.api_key(db.get_settings()["hermes"].get("api_key") or None))


phone.get_brain = lambda: get_brain()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    services.start()
    task = asyncio.create_task(scheduler.loop())
    upd = asyncio.create_task(_update_loop())
    inbox = asyncio.create_task(public.inbox_loop()) if not os.environ.get("JARVIS_NO_SUPERVISOR") else None
    rout = asyncio.create_task(routines.loop()) if not os.environ.get("JARVIS_NO_SUPERVISOR") else None
    asyncio.create_task(_open_window_for_wake())
    yield
    task.cancel()
    upd.cancel()
    if inbox:
        inbox.cancel()
    if rout:
        rout.cancel()
    services.stop_all()


async def _update_loop():
    """Check GitHub for a new version shortly after start, then every 6 hours."""
    if os.environ.get("JARVIS_NO_SUPERVISOR"):
        return
    await asyncio.sleep(20)
    while True:
        await updater.check()
        await asyncio.sleep(6 * 3600)


app = FastAPI(title="JARVIS", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def localhost_only(request: Request, call_next):
    # Defense in depth: even if bound wider by mistake, refuse non-local clients.
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        return JSONResponse({"detail": "JARVIS only accepts local connections"}, status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------- status & setup

@app.get("/api/status")
async def status():
    settings = db.get_settings()
    agent = await agent_client.status()
    el_key, el_src = secrets_store.get_secret("elevenlabs_api_key", env="ELEVENLABS_API_KEY")
    if brain_override is not None:
        brain = {"ready": True, "state": "running", "detail": "", "model": "test", "installed": True, "model_configured": True}
    else:
        h = await get_brain().health()
        g = services.gateway.info()
        detail = h["error"] if h["reachable"] else (g["detail"] or h["error"])  # show Hermes's own log when it died
        brain = {"ready": bool(h["authorized"]), "state": g["state"], "detail": detail,
                 "model": h["model"], "installed": bool(services.hermes_bin()) or h["reachable"],
                 "model_configured": hermes.model_configured(), "restarts": g["restarts"]}
    return {
        "brain": brain,
        "agent": {**agent, "service": services.agent.info()},
        "voice": {"elevenlabs": bool(el_key), "key_source": el_src, "key_hint": secrets_store.mask(el_key),
                  "provider": settings["voice"].get("provider", "elevenlabs")},
        "browser": {"available": (ROOT / "mcp-runtime" / "node_modules" / "@playwright" / "mcp").exists()},
        "phone": phone.status(),
        "update": {"available": updater.info()["available"]},
        "google": google.status(),
        "emergency_stop": settings.get("emergency_stop", False),
        "user_name": settings.get("user_name", ""),
        "platform": sys.platform,
        "counts": {
            "pending_approvals": db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"],
            "open_tasks": db.one("SELECT COUNT(*) n FROM tasks WHERE status IN ('todo','queued','proposed','running')")["n"],
            "memories": db.one("SELECT COUNT(*) n FROM memories")["n"],
            "conversations": db.one("SELECT COUNT(*) n FROM conversations")["n"],
        },
    }


class KeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)


@app.post("/api/setup/elevenlabs")
async def set_elevenlabs_key(body: KeyIn):
    key = "".join(body.api_key.split())  # drop spaces/newlines picked up when copying
    try:
        info = await voice.check_key(key)
    except voice.VoiceError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't reach ElevenLabs: {type(e).__name__}")
    where = secrets_store.set_secret("elevenlabs_api_key", key)
    db.log_activity("ElevenLabs API key saved", "info", tool="settings", source="user", result={"stored_in": where})
    return {"ok": True, "stored_in": where, **info}


@app.delete("/api/setup/elevenlabs")
async def delete_elevenlabs_key():
    secrets_store.delete_secret("elevenlabs_api_key")
    db.log_activity("ElevenLabs API key removed", "info", tool="settings", source="user")
    return {"ok": True}


@app.post("/api/hermes/setup")
async def hermes_setup():
    """Open Terminal with Hermes's own model/provider picker (macOS)."""
    binary = services.hermes_bin()
    if not binary:
        raise HTTPException(412, "Hermes Agent isn't installed. Run the JARVIS installer.")
    if sys.platform != "darwin":
        raise HTTPException(400, f"Run this in a terminal: {binary} model")
    script = DATA_DIR / "choose-hermes-model.command"
    script.write_text(f"""#!/bin/bash
clear
echo "Choose the AI model JARVIS (Hermes) should use."
echo
"{binary}" model
echo
echo "Done. JARVIS will restart Hermes with your choice."
curl -s -X POST http://127.0.0.1:{BACKEND_PORT}/api/hermes/restart >/dev/null
sleep 2
osascript -e 'tell application "Terminal" to close front window' >/dev/null 2>&1 &
""")
    script.chmod(0o700)
    subprocess.Popen(["open", str(script)])
    return {"ok": True}


@app.post("/api/hermes/restart")
async def hermes_restart():
    await services.restart_gateway()
    return {"ok": True, "hermes": services.gateway.info()}


@app.post("/api/services/restart")
async def services_restart():
    db.log_activity("Restarted JARVIS's helpers (Hermes, Mac agent, phone)", "info", tool="system", source="user")
    await services.restart_all()
    return {"ok": True}


@app.post("/api/agent/restart")
async def agent_restart():
    services.agent.stop()
    services.agent.restarts = 0
    await services._ensure_agent()
    return {"ok": True, "agent": services.agent.info()}


# ---------------------------------------------------------------- wake word

LOCAL_ORIGINS = {f"http://127.0.0.1:{BACKEND_PORT}", f"http://localhost:{BACKEND_PORT}",
                 "http://127.0.0.1:5173", "http://localhost:5173"}


@app.websocket("/api/wake/ws")
async def wake_ws(ws: WebSocket):
    # WebSockets skip CORS, so only the JARVIS window itself may connect.
    if ws.headers.get("origin") not in LOCAL_ORIGINS:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        await wake.serve(ws, float(db.get_settings()["wake"].get("threshold", 0.5)))
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------- Google (Gmail + Calendar)

class GoogleIn(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    business_hours: dict | None = None
    slot_minutes: int | None = Field(default=None, ge=10, le=240)
    min_notice_hours: float | None = Field(default=None, ge=0, le=168)


def _google_view() -> dict:
    g = db.get_settings()["google"]
    return {"status": google.status(), "settings": {k: g.get(k) for k in
            ("client_id", "email", "business_hours", "slot_minutes", "min_notice_hours")}}


@app.get("/api/google")
async def google_get():
    return _google_view()


@app.put("/api/google")
async def google_put(body: GoogleIn):
    g = db.get_settings()["google"]
    if body.client_id is not None:
        cid = body.client_id.strip()
        if cid and not cid.endswith(".apps.googleusercontent.com"):
            raise HTTPException(400, "That doesn't look like a Google OAuth client ID (it ends in .apps.googleusercontent.com).")
        g["client_id"] = cid
    if body.client_secret:
        secrets_store.set_secret("google_client_secret", body.client_secret.strip())
    if body.business_hours is not None:
        bh = body.business_hours
        days = [int(d) for d in bh.get("days", []) if 1 <= int(d) <= 7]
        for k in ("start", "end"):
            if not re.fullmatch(r"\d{2}:\d{2}", str(bh.get(k, ""))):
                raise HTTPException(400, "Working hours must look like 09:00")
        if bh["start"] >= bh["end"]:
            raise HTTPException(400, "Working hours must end after they start")
        g["business_hours"] = {"days": days or [1, 2, 3, 4, 5], "start": bh["start"], "end": bh["end"]}
    if body.slot_minutes is not None:
        g["slot_minutes"] = body.slot_minutes
    if body.min_notice_hours is not None:
        g["min_notice_hours"] = body.min_notice_hours
    db.set_setting("google", g)
    return _google_view()


@app.get("/api/google/connect")
async def google_connect():
    from fastapi.responses import RedirectResponse
    try:
        return RedirectResponse(google.auth_url())
    except google.GoogleError as e:
        raise HTTPException(400, str(e))


@app.get("/api/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import HTMLResponse
    if error:
        msg, ok = f"Google sign-in was cancelled ({html_escape(error)}).", False
    else:
        try:
            email = await google.finish_auth(code, state)
            msg, ok = f"Connected {html_escape(email or 'your Google account')}.", True
        except google.GoogleError as e:
            msg, ok = html_escape(str(e)), False
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><title>JARVIS · Google</title>
<body style="background:#000;color:#e6eef5;font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><p style="font-size:22px;color:{'#4be3a2' if ok else '#ff5a6a'}">{msg}</p>
<p><a style="color:#3ce7ff" href="/#settings">Back to JARVIS</a></p></div>
<script>setTimeout(()=>location.href='/#settings',{1800 if ok else 6000})</script></body>""")


@app.delete("/api/google")
async def google_delete():
    google.disconnect()
    db.log_activity("Google disconnected", "info", tool="google", source="user")
    return _google_view()


# ---------------------------------------------------------------- reminders & briefing

class ReminderIn(BaseModel):
    text: str
    at: str
    via: str = "text"


@app.get("/api/reminders")
async def reminders_get():
    return routines.list_reminders()


@app.post("/api/reminders")
async def reminders_add(body: ReminderIn):
    try:
        return routines.add_reminder(body.text, body.at, body.via)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/reminders/{rid}")
async def reminders_cancel(rid: int):
    return {"cancelled": routines.cancel_reminder(rid)}


@app.post("/api/briefing/now")
async def briefing_now():
    try:
        return await routines.send_briefing()
    except Exception as e:
        raise HTTPException(502, f"Couldn't send the briefing: {e}")


@app.get("/api/system")
async def system_metrics():
    """Live CPU / memory / disk for the Command Center (read-only, not logged)."""
    import psutil
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(str(Path.home()))
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    net = psutil.net_if_stats()
    online = any(s.isup for n, s in net.items() if not n.startswith("lo"))
    return {"cpu": psutil.cpu_percent(interval=None), "ram": vm.percent, "disk": du.percent,
            "battery": None if not bat else {"percent": round(bat.percent), "plugged": bat.power_plugged},
            "network": online, "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1)}


@app.get("/api/wake")
async def wake_info():
    return {"available": wake.available(), "listening_windows": wake.STATE["clients"],
            "last_wake": wake.STATE["last_wake"], "error": wake.STATE["error"]}


async def _open_window_for_wake():
    """At login, open the JARVIS window (in the background) so it can hear 'Hey JARVIS'."""
    if sys.platform != "darwin" or os.environ.get("JARVIS_NO_SUPERVISOR"):
        return
    await asyncio.sleep(25)
    w = db.get_settings()["wake"]
    if not (w.get("enabled") and w.get("open_at_login")) or wake.STATE["clients"]:
        return
    for app_path in ("/Applications/JARVIS.app", os.path.expanduser("~/Applications/JARVIS.app")):
        if os.path.isdir(app_path):
            subprocess.Popen(["open", "-g", app_path])
            break


@app.get("/api/update")
async def update_info():
    return updater.info()


@app.post("/api/update/check")
async def update_check():
    return await updater.check()


@app.post("/api/update/apply")
async def update_apply():
    try:
        r = await updater.apply()
    except Exception as e:
        raise HTTPException(502, f"Update failed: {e}")
    db.log_activity(f"Updating JARVIS to {(r.get('latest') or {}).get('sha', '?')[:7]}", "info", tool="system", source="user")
    return r


@app.post("/api/shutdown")
async def shutdown():
    """Quit JARVIS: stops Hermes, the agent and this backend."""
    db.log_activity("JARVIS shut down from the dashboard", "info", tool="system", source="user")

    async def later():
        await asyncio.sleep(0.5)
        services.stop_all()
        os._exit(0)   # a clean exit: launchd only restarts JARVIS after a crash
    asyncio.create_task(later())
    return {"ok": True}


# ---------------------------------------------------------------- settings / permissions / safety

ALLOWED_SETTINGS = {"user_name", "assistant_name", "voice", "memory", "hermes", "browser", "wake", "receptionist", "router", "briefing"}


@app.get("/api/settings")
async def get_settings():
    return {"settings": db.get_settings(), "integrations": integrations.all_status()}


@app.put("/api/settings")
async def put_settings(body: dict):
    for k, v in body.items():
        if k not in ALLOWED_SETTINGS:
            raise HTTPException(400, f"Unknown or protected setting: {k}")
        db.set_setting(k, v)
    if "router" in body:   # routes live in Hermes's config, so restart it to apply them
        asyncio.create_task(services.restart_gateway())
    if "browser" in body:  # read by the jarvis MCP server when it (re)starts Playwright
        (DATA_DIR / "browser_settings.json").write_text(json.dumps(db.get_settings()["browser"]))
    return {"settings": db.get_settings()}


class PermissionsIn(BaseModel):
    approved_apps: list[str]
    approved_domains: list[str]
    approved_directories: list[str]
    approval_required: list[str]
    disabled_tools: list[str]
    browser: dict = Field(default_factory=dict)
    obsidian_vault: str = ""


@app.get("/api/permissions")
async def get_permissions():
    return load_permissions()


@app.put("/api/permissions")
async def put_permissions(body: PermissionsIn):
    data = body.model_dump()
    for d in data["approved_directories"]:
        if d.strip() in ("/", "~", "~/") or d.strip().startswith("/System"):
            raise HTTPException(400, f"'{d}' is too broad to approve")
    for dom in data["approved_domains"]:
        if "/" in dom or " " in dom or not dom.strip():
            raise HTTPException(400, f"'{dom}' should be a bare domain like example.com")
    if data["obsidian_vault"].strip():
        v = Path(os.path.expanduser(data["obsidian_vault"].strip()))
        if not (v / ".obsidian").is_dir():
            raise HTTPException(400, f"'{data['obsidian_vault']}' isn't an Obsidian vault (no .obsidian folder inside).")
    data["migrations"] = load_permissions().get("migrations", [])  # keep one-time upgrades applied
    save_permissions(data)
    db.log_activity("Permissions updated", "info", tool="settings", source="user")
    return load_permissions()


@app.post("/api/emergency-stop")
async def emergency_stop():
    db.set_setting("emergency_stop", True)
    agent_ok = await agent_client.control("stop")
    db.ex("UPDATE tasks SET status='cancelled', updated_at=? WHERE status IN ('queued')", (db.now(),))
    for cid in list(chat._cancel):
        chat.request_stop(cid)
    db.log_activity("EMERGENCY STOP engaged", "info", tool="safety", source="user", result={"agent_notified": agent_ok})
    return {"emergency_stop": True, "agent_notified": agent_ok}


@app.post("/api/resume")
async def resume():
    db.set_setting("emergency_stop", False)
    agent_ok = await agent_client.control("resume")
    db.log_activity("Emergency stop released", "info", tool="safety", source="user")
    return {"emergency_stop": False, "agent_notified": agent_ok}


# ---------------------------------------------------------------- chat

class ChatIn(BaseModel):
    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=20000)


@app.post("/api/chat")
async def chat_endpoint(body: ChatIn):
    brain = get_brain()

    async def gen():
        # If the browser disconnects (stop button / window closed) Starlette cancels this
        # generator, which closes the Hermes stream (Hermes then interrupts the run).
        async for ev in chat.run_chat(body.conversation_id, body.message, brain):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/stop")
async def chat_stop(body: dict):
    return {"stopped": chat.request_stop(str(body.get("conversation_id", "")))}


@app.get("/api/conversations")
async def list_conversations(q: str = ""):
    if q:
        return db.q("SELECT DISTINCT c.* FROM conversations c JOIN messages m ON m.conversation_id=c.id "
                    "WHERE m.text LIKE ? OR c.title LIKE ? ORDER BY c.updated_at DESC LIMIT 100", (f"%{q}%", f"%{q}%"))
    return db.q("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100")


@app.post("/api/conversations")
async def new_conversation():
    return chat.create_conversation()


@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    c = db.one("SELECT * FROM conversations WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "not found")
    return {**c, "messages": chat.display_messages(cid)}


@app.patch("/api/conversations/{cid}")
async def rename_conversation(cid: str, body: dict):
    db.ex("UPDATE conversations SET title=? WHERE id=?", (str(body.get("title", ""))[:120] or "Untitled", cid))
    return db.one("SELECT * FROM conversations WHERE id=?", (cid,))


@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    db.ex("DELETE FROM messages WHERE conversation_id=?", (cid,))
    db.ex("DELETE FROM conversations WHERE id=?", (cid,))
    return {"ok": True}


# ---------------------------------------------------------------- memory

class MemoryIn(BaseModel):
    kind: str
    content: str = Field(min_length=1, max_length=4000)


class MemoryPatch(BaseModel):
    kind: Optional[str] = None
    content: Optional[str] = None


@app.get("/api/memories")
async def list_memories(q: str = "", kind: Optional[str] = None):
    return memory.search(q, kind)


@app.post("/api/memories")
async def add_memory(body: MemoryIn):
    try:
        return memory.create(body.kind, body.content, source="user")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/memories/{mid}")
async def edit_memory(mid: int, body: MemoryPatch):
    try:
        m = memory.update(mid, body.kind, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not m:
        raise HTTPException(404, "not found")
    return m


@app.delete("/api/memories/{mid}")
async def delete_memory(mid: int):
    db.ex("DELETE FROM memories WHERE id=?", (mid,))
    return {"ok": True}


@app.get("/api/memories/export")
async def export_memories():
    data = {"exported_at": db.now(), "memories": db.q("SELECT * FROM memories ORDER BY id")}
    return JSONResponse(data, headers={"Content-Disposition": "attachment; filename=jarvis-memories.json"})


# ---------------------------------------------------------------- tasks & automations

class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    due_at: Optional[str] = None
    steps: Optional[list[dict]] = None


@app.get("/api/tasks")
async def list_tasks(status: Optional[str] = None):
    sql, p = "SELECT * FROM tasks", []
    if status:
        sql += " WHERE status=?"; p.append(status)
    rows = db.q(sql + " ORDER BY CASE WHEN status IN ('proposed','running','queued') THEN 0 ELSE 1 END, id DESC LIMIT 300", p)
    for r in rows:
        r["steps"] = json.loads(r["steps"]) if r["steps"] else None
    return rows


@app.post("/api/tasks")
async def add_task(body: TaskIn):
    if body.steps:  # a user-created automation is approved by its creator
        for s in body.steps:
            if not isinstance(s.get("tool"), str) or not isinstance(s.get("args", {}), dict):
                raise HTTPException(400, "each step needs a tool name and args object")
        t = actions.create_task(body.title, body.description, body.due_at, body.steps, status="queued", source="user")
        db.ex("UPDATE tasks SET approved=1 WHERE id=?", (t["id"],))
    else:
        t = actions.create_task(body.title, body.description, body.due_at)
    db.log_activity(f"Task created: {body.title}", "info", tool="tasks", source="user")
    return t


@app.patch("/api/tasks/{tid}")
async def edit_task(tid: int, body: dict):
    allowed = {"title", "description", "due_at", "status"}
    sets = {k: v for k, v in body.items() if k in allowed}
    if sets.get("status") and sets["status"] not in ("todo", "done", "cancelled"):
        raise HTTPException(400, "status can be set to todo, done or cancelled")
    if not sets:
        raise HTTPException(400, "nothing to update")
    db.ex(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?", (*sets.values(), db.now(), tid))
    return db.one("SELECT * FROM tasks WHERE id=?", (tid,))


@app.post("/api/tasks/{tid}/approve")
async def approve_task(tid: int):
    cur = db.ex("UPDATE tasks SET approved=1, status='queued', updated_at=? WHERE id=? AND status='proposed'", (db.now(), tid))
    if cur.rowcount != 1:
        raise HTTPException(409, "Task is not awaiting approval")
    db.log_activity(f"Automation #{tid} approved", "info", tool="automation", approval="approved", source="user")
    return {"ok": True}


@app.post("/api/tasks/{tid}/run")
async def rerun_task(tid: int):
    cur = db.ex("UPDATE tasks SET status='queued', due_at=NULL, updated_at=? WHERE id=? AND approved=1 AND steps IS NOT NULL "
                "AND status IN ('completed','failed','cancelled')", (db.now(), tid))
    if cur.rowcount != 1:
        raise HTTPException(409, "Only finished, approved automations can be re-run")
    return {"ok": True}


@app.post("/api/tasks/{tid}/cancel")
async def cancel_task(tid: int):
    db.ex("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=? AND status IN ('todo','proposed','queued')", (db.now(), tid))
    return db.one("SELECT * FROM tasks WHERE id=?", (tid,))


@app.delete("/api/tasks/{tid}")
async def delete_task(tid: int):
    db.ex("DELETE FROM tasks WHERE id=? AND status != 'running'", (tid,))
    return {"ok": True}


# ---------------------------------------------------------------- approvals, tools, activity

@app.get("/api/approvals")
async def list_approvals(status: str = "pending"):
    rows = db.q("SELECT * FROM approvals WHERE status=? ORDER BY id DESC LIMIT 100", (status,)) if status != "all" \
        else db.q("SELECT * FROM approvals ORDER BY id DESC LIMIT 100")
    for r in rows:
        r["args"] = json.loads(r["args"])
    return rows


@app.post("/api/approvals/{aid}/{decision}")
async def decide(aid: int, decision: str):
    if decision not in ("approve", "deny"):
        raise HTTPException(404, "unknown decision")
    try:
        return await actions.decide_approval(aid, decision == "approve")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/agent/tools")
async def agent_tools():
    data = await agent_client.tools(force=True)
    return data or {"tools": [], "offline": True}


class RunIn(BaseModel):
    tool: str
    args: dict[str, Any] = {}


@app.post("/api/tools/run")
async def run_tool(body: RunIn):
    """Quick actions clicked by the user in the dashboard (the click is the approval)."""
    return await actions.run_tool(body.tool, body.args, user_initiated=True, source="user")


@app.get("/api/activity")
async def activity(limit: int = 200, status: Optional[str] = None):
    if status:
        return db.q("SELECT * FROM activity WHERE status=? ORDER BY id DESC LIMIT ?", (status, min(limit, 1000)))
    return db.q("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (min(limit, 1000),))


# ---------------------------------------------------------------- phone (Twilio)

class PhoneIn(BaseModel):
    enabled: bool = False
    account_sid: str = ""
    auth_token: Optional[str] = None      # only sent when changing it
    twilio_number: str = ""
    owner_number: str = ""
    language: str = "en-GB"


@app.get("/api/phone")
async def get_phone():
    c = phone.cfg()
    return {"settings": {k: c.get(k, "") for k in ("enabled", "account_sid", "twilio_number", "owner_number", "language")},
            "status": phone.status(), "cloudflared": bool(services.cloudflared_bin())}


@app.put("/api/phone")
async def put_phone(body: PhoneIn):
    sid = body.account_sid.strip()
    if sid and not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid):
        raise HTTPException(400, "Account SID should look like AC followed by 32 letters/numbers (Twilio Console → Account Info).")
    for label, num in (("Twilio number", body.twilio_number), ("Your number", body.owner_number)):
        n = phone.normalize(num)
        if num and not re.fullmatch(r"\+\d{8,15}", n):
            raise HTTPException(400, f"{label} must be in international format, like +39 345 123 4567.")
    if body.auth_token:
        tok = body.auth_token.strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", tok):
            raise HTTPException(400, "Auth Token should be 32 letters/numbers (Twilio Console → Account Info).")
        secrets_store.set_secret("twilio_auth_token", tok)
    cur = db.get_settings().get("phone") or {}
    db.set_setting("phone", {**cur, "enabled": body.enabled, "account_sid": sid,
                             "twilio_number": phone.normalize(body.twilio_number),
                             "owner_number": phone.normalize(body.owner_number), "language": body.language or "en-GB"})
    db.log_activity("Phone settings updated", "info", tool="settings", source="user")
    if phone.configured():
        try:
            await phone._api("GET", ".json")   # checks the SID + token
        except Exception as e:
            raise HTTPException(400, str(e))
    await services.restart_phone()
    return await get_phone()


@app.post("/api/phone/test-call")
async def phone_test_call():
    try:
        return await phone.call_owner("Hello, it's JARVIS. This is a test call. Say something and I'll answer.")
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/phone/test-sms")
async def phone_test_sms():
    try:
        return await phone.sms_owner("JARVIS here. Texting works. Reply to this message to talk to me.")
    except Exception as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- voice (ElevenLabs)

def _voice_http(e: voice.VoiceError):
    return HTTPException(e.status, str(e))


@app.post("/api/voice/stt")
async def voice_stt(audio: UploadFile = File(...), language: str = Form("")):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "No audio received")
    if len(data) > 25_000_000:
        raise HTTPException(413, "Recording too long")
    lang = language or db.get_settings()["voice"].get("stt_language") or None
    try:
        text = await voice.transcribe(data, audio.filename or "speech.webm", audio.content_type or "audio/webm",
                                      language=lang)
    except voice.VoiceError as e:
        raise _voice_http(e)
    return {"text": text}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@app.post("/api/voice/tts")
async def voice_tts(body: SpeakIn):
    v = db.get_settings()["voice"]
    try:
        stream = await voice.speak(body.text, v.get("voice_id") or None, v.get("tts_model") or None)
    except voice.VoiceError as e:
        raise _voice_http(e)
    return StreamingResponse(stream, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/voice/voices")
async def voice_voices():
    try:
        return {"voices": await voice.voices()}
    except voice.VoiceError as e:
        raise _voice_http(e)


@app.get("/api/voice/models")
async def voice_models():
    try:
        return {"models": await voice.models()}
    except voice.VoiceError as e:
        raise _voice_http(e)


# ---------------------------------------------------------------- internal: called by the jarvis MCP server

def internal_auth(authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization.encode(), f"Bearer {agent_token()}".encode()):
        raise HTTPException(401, "unauthorized")


APPROVAL_WAIT = float(os.getenv("JARVIS_APPROVAL_WAIT", "240"))


@app.get("/api/internal/tools", dependencies=[Depends(internal_auth)])
async def internal_tools():
    defs, meta = await actions.claude_tools()
    return {"tools": defs, "emergency_stop": db.get_settings().get("emergency_stop", False)}


class InternalCall(BaseModel):
    tool: str
    args: dict[str, Any] = {}
    page_url: Optional[str] = None


def public_auth(authorization: str = Header(default="")):
    from shared.settings import private_token
    if not secrets.compare_digest(authorization.encode(), f"Bearer {private_token('public_mcp_token')}".encode()):
        raise HTTPException(401, "unauthorized")


@app.get("/api/internal/public/tools", dependencies=[Depends(public_auth)])
async def public_tools():
    return {"tools": public.tool_list()}


@app.post("/api/internal/public/run", dependencies=[Depends(public_auth)])
async def public_run(body: InternalCall):
    names = {t["name"] for t in public.tool_list()}
    if body.tool not in names:
        return {"status": "error", "error": f"Unknown tool {body.tool}"}
    try:
        return {"status": "ok", "output": await public.run(body.tool, body.args)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


@app.post("/api/internal/run", dependencies=[Depends(internal_auth)])
async def internal_run(body: InternalCall):
    res = await actions.run_tool(body.tool, body.args, conversation_id=chat.ACTIVE["cid"], source="hermes",
                                 wait=APPROVAL_WAIT)
    if res.get("status") == "ok":   # privacy guard: keys, passwords and one-time codes never reach the model
        from . import redact
        res["output"], n = redact.redact_obj(res.get("output"))
        if n:
            db.log_activity(f"Privacy guard redacted {n} secret(s) from {body.tool} output", "info", tool="privacy")
    return res


@app.post("/api/internal/authorize", dependencies=[Depends(internal_auth)])
async def internal_authorize(body: InternalCall):
    """Browser (Playwright MCP) actions: allow, deny, or block until the user decides."""
    if db.get_settings().get("emergency_stop"):
        return {"decision": "deny", "reason": "Emergency stop is active — no actions will run until it is released."}
    decision, reason = browser_policy.assess(body.tool, body.args, load_permissions(), body.page_url)
    if decision != "ask":
        return {"decision": decision, "reason": reason}
    aid = actions.create_approval(body.tool, body.args, kind="external", conversation_id=chat.ACTIVE["cid"],
                                  reason=reason, source="hermes")
    row = await actions.wait_for_decision(aid, APPROVAL_WAIT)
    if row["status"] == "approved":
        return {"decision": "allow", "reason": "approved by you", "approval_id": aid}
    if row["status"] == "expired":
        return {"decision": "deny", "approval_id": aid,
                "reason": f"Nobody approved this within {int(APPROVAL_WAIT)}s, so it did not run. Ask the user to approve and try again."}
    return {"decision": "deny", "reason": "The user denied this action. Don't retry it unless they ask.", "approval_id": aid}


class InternalReport(BaseModel):
    tool: str
    args: dict[str, Any] = {}
    ok: bool
    summary: str = ""
    approval_id: Optional[int] = None


@app.post("/api/internal/report", dependencies=[Depends(internal_auth)])
async def internal_report(body: InternalReport):
    summary = actions.describe_call(body.tool, body.args)
    db.log_activity(summary, "ok" if body.ok else "error", tool=body.tool,
                    approval="approved" if body.approval_id else "auto",
                    result=None if not body.ok else body.summary[:2000], error=None if body.ok else body.summary[:500],
                    source="hermes")
    if body.approval_id:
        db.ex("UPDATE approvals SET status=?, result=? WHERE id=?",
              ("executed" if body.ok else "failed", body.summary[:20000], body.approval_id))
    return {"ok": True}


# ---------------------------------------------------------------- built dashboard

DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        f = (DIST / path).resolve()
        if path and f.is_file() and f.is_relative_to(DIST.resolve()):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")


def main():
    fh = RotatingFileHandler(Path(LOG_DIR) / "backend.log", maxBytes=2_000_000, backupCount=3)
    handlers: list[logging.Handler] = [fh]
    if sys.stderr.isatty():          # under launchd stdout goes to app.out, which isn't rotated
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "uvicorn.access"):   # health checks every few seconds
        logging.getLogger(noisy).setLevel(logging.WARNING)
    uvicorn.run("backend.main:app", host=BACKEND_HOST, port=BACKEND_PORT, log_level="warning",
                log_config=None)


if __name__ == "__main__":
    main()
