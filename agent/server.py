"""JARVIS Mac agent HTTP service. Binds to 127.0.0.1 and requires a bearer token.

Run: python -m agent.server
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal
import sys
import time
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from shared.settings import AGENT_HOST, AGENT_PORT, DATA_DIR, LOG_DIR, agent_token, load_permissions

from . import VERSION
from . import tools as _tools  # noqa: F401  (registers built-in tools)
from .registry import ToolError, registry

log = logging.getLogger("jarvis.agent")
SECRET_KEYS = ("token", "password", "secret", "api_key", "apikey", "authorization", "cookie")


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if any(s in k.lower() for s in SECRET_KEYS) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 300:
        return obj[:300] + "…"
    return obj


class State:
    started = time.time()
    stopped = False                       # emergency stop
    results: "OrderedDict[str, dict]" = OrderedDict()   # idempotency cache
    inflight: set[str] = set()
    executed = 0
    failed = 0


state = State()
TOKEN = agent_token()
app = FastAPI(title="JARVIS Mac Agent", version=VERSION, docs_url=None, redoc_url=None)


def auth(authorization: str = Header(default="")):
    expected = f"Bearer {TOKEN}"
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


class ExecuteRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=100)
    tool: str = Field(max_length=100)
    args: dict = Field(default_factory=dict)
    approved: bool = False


@app.get("/health")
def health():
    # Unauthenticated liveness probe; reveals nothing sensitive.
    return {"ok": True}


@app.get("/status", dependencies=[Depends(auth)])
def status():
    return {"ok": True, "version": VERSION, "platform": sys.platform, "pid": os.getpid(),
            "uptime_s": round(time.time() - state.started), "stopped": state.stopped,
            "executed": state.executed, "failed": state.failed, "tool_count": len(registry.tools)}


@app.get("/tools", dependencies=[Depends(auth)])
def list_tools():
    perms = load_permissions()
    return {"tools": registry.describe(perms), "permissions": perms, "platform": sys.platform}


@app.post("/control/stop", dependencies=[Depends(auth)])
def control_stop():
    state.stopped = True
    log.warning("EMERGENCY STOP engaged — all tool execution disabled")
    return {"stopped": True}


@app.post("/control/resume", dependencies=[Depends(auth)])
def control_resume():
    state.stopped = False
    log.warning("Emergency stop released")
    return {"stopped": False}


@app.post("/execute", dependencies=[Depends(auth)])
async def execute(req: ExecuteRequest):
    if req.request_id in state.results:          # duplicate delivery → same result, no re-run
        return {**state.results[req.request_id], "duplicate": True}
    if req.request_id in state.inflight:
        raise HTTPException(409, "request already running")
    if state.stopped:
        return {"ok": False, "error": "Emergency stop is active; no actions will be executed."}

    perms = load_permissions()
    started = time.time()
    state.inflight.add(req.request_id)
    try:
        tool = registry.validate(req.tool, req.args)
        if tool.name in perms["disabled_tools"]:
            raise ToolError(f"Tool '{tool.name}' is disabled in permissions")
        needs_approval = tool.sensitive or tool.name in perms["approval_required"]
        if needs_approval and not req.approved:
            raise ToolError(f"Tool '{tool.name}' requires explicit user approval")
        output = await asyncio.wait_for(asyncio.to_thread(tool.handler, req.args, perms), timeout=tool.timeout)
        result = {"ok": True, "output": output}
        state.executed += 1
    except asyncio.TimeoutError:
        result = {"ok": False, "error": "Tool timed out"}
        state.failed += 1
    except ToolError as e:
        result = {"ok": False, "error": str(e)}
        state.failed += 1
    except Exception as e:  # never crash the service because of a tool
        log.exception("tool %s crashed", req.tool)
        result = {"ok": False, "error": f"Tool failed: {type(e).__name__}: {e}"[:400]}
        state.failed += 1
    finally:
        state.inflight.discard(req.request_id)

    result["duration_ms"] = int((time.time() - started) * 1000)
    state.results[req.request_id] = result
    while len(state.results) > 500:
        state.results.popitem(last=False)
    log.info("tool=%s approved=%s ok=%s args=%s err=%s", req.tool, req.approved, result["ok"],
             redact(req.args), result.get("error"))
    return result


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG_DIR / "agent.log", maxBytes=2_000_000, backupCount=3)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root = logging.getLogger("jarvis")
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)


def main():
    setup_logging()
    if AGENT_HOST not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Agent bound to %s — it should only listen on localhost!", AGENT_HOST)
    pidfile = DATA_DIR / "agent.pid"
    pidfile.write_text(str(os.getpid()))
    log.info("JARVIS agent %s starting on %s:%s (%d tools)", VERSION, AGENT_HOST, AGENT_PORT, len(registry.tools))
    try:
        uvicorn.run(app, host=AGENT_HOST, port=AGENT_PORT, log_level="warning")  # handles SIGINT/SIGTERM gracefully
    finally:
        pidfile.unlink(missing_ok=True)
        log.info("JARVIS agent stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGHUP, signal.SIG_IGN) if hasattr(signal, "SIGHUP") else None
    main()
