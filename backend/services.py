"""Keeps JARVIS's helper processes alive: the Mac agent and the Hermes gateway.

The backend is the one long-running process (started by JARVIS.app or at login);
it launches the others, restarts them if they crash, and stops them on shutdown.
If a service is already running (e.g. the agent's LaunchAgent), it's reused.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from shared.settings import AGENT_URL, HERMES_PORT, HERMES_URL, LOG_DIR, ROOT

from . import db, hermes, phone

log = logging.getLogger("jarvis.services")


class Service:
    def __init__(self, name: str, health_url: str):
        self.name = name
        self.health_url = health_url
        self.proc: subprocess.Popen | None = None
        self.state = "stopped"     # stopped | starting | running | external | failed | unavailable
        self.detail = ""
        self.restarts = 0
        self._last_start = 0.0
        self._log = None

    async def healthy(self, headers: dict | None = None) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(self.health_url, headers=headers or {})
                return r.status_code < 500
        except httpx.HTTPError:
            return False

    def spawn(self, argv: list[str], env: dict | None = None) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._log = open(LOG_DIR / f"{self.name}.out", "ab")
        self.proc = subprocess.Popen(argv, cwd=str(ROOT), stdout=self._log, stderr=subprocess.STDOUT,
                                     env={**os.environ, **(env or {})}, start_new_session=True)
        self._last_start = time.time()
        self.state = "starting"
        log.info("started %s (pid %s)", self.name, self.proc.pid)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self._log:
            self._log.close()
            self._log = None
        if self.state in ("running", "starting"):
            self.state = "stopped"

    def info(self) -> dict:
        return {"state": self.state, "detail": self.detail, "restarts": self.restarts,
                "pid": self.proc.pid if self.proc and self.proc.poll() is None else None}


agent = Service("agent", f"{AGENT_URL}/health")
gateway = Service("hermes", f"{HERMES_URL}/health")
_task: asyncio.Task | None = None


def hermes_bin() -> str | None:
    return hermes.find_binary(db.get_settings().get("hermes", {}).get("binary") or None)


async def _ensure_agent() -> None:
    if agent.proc and agent.proc.poll() is None:
        if await agent.healthy():
            agent.state = "running"
        return
    if await agent.healthy():
        agent.state, agent.detail = "external", "already running (LaunchAgent or another terminal)"
        return
    if agent.proc and agent.proc.poll() is not None:
        agent.restarts += 1
        if time.time() - agent._last_start < 5 * min(agent.restarts, 6):
            return  # back off
    agent.spawn([sys.executable, "-m", "agent.server"])


async def _ensure_gateway() -> None:
    client = hermes.HermesClient(key=hermes.api_key(db.get_settings().get("hermes", {}).get("api_key") or None))
    if gateway.proc and gateway.proc.poll() is None:
        h = await client.health()
        gateway.state = "running" if h["authorized"] else "starting"
        gateway.detail = h["error"] or ""
        return
    h = await client.health()
    if h["reachable"]:
        gateway.state = "external" if h["authorized"] else "failed"
        gateway.detail = h["error"] or "using an already-running Hermes gateway"
        return
    binary = hermes_bin()
    if not binary:
        gateway.state, gateway.detail = "unavailable", "Hermes Agent isn't installed. Run the JARVIS installer again."
        return
    if gateway.proc and gateway.proc.poll() is not None:
        gateway.restarts += 1
        tail = _tail(LOG_DIR / "hermes.out")
        gateway.detail = f"Hermes stopped unexpectedly. Last log lines:\n{tail}"
        if time.time() - gateway._last_start < 10 * min(gateway.restarts, 6):
            gateway.state = "failed"
            return
    try:
        hermes.ensure_config()
        hermes.ensure_env(key=client.key)
    except Exception as e:  # never block startup on config edits
        log.warning("couldn't update Hermes config: %s", e)
    gateway.spawn([binary, "gateway", "run"], env={
        "API_SERVER_ENABLED": "true",
        "API_SERVER_KEY": client.key,
        "API_SERVER_HOST": "127.0.0.1",
        "API_SERVER_PORT": str(HERMES_PORT),
    })


def _tail(path: Path, n: int = 6) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


# ---------------------------------------------------------------- phone line (Twilio)

PHONE_PORT = int(os.getenv("JARVIS_PHONE_PORT", "8010"))
tunnel = Service("tunnel", f"http://127.0.0.1:{PHONE_PORT}/twilio/health")
_phone_server: asyncio.Task | None = None
_TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def cloudflared_bin() -> str | None:
    for c in (os.getenv("JARVIS_CLOUDFLARED"), shutil.which("cloudflared"), "/opt/homebrew/bin/cloudflared",
              "/usr/local/bin/cloudflared"):
        if c and os.path.exists(c):
            return c
    return None


async def _start_phone_server() -> None:
    """The public-facing server: only the /twilio routes, on its own port."""
    global _phone_server
    if _phone_server and not _phone_server.done():
        return
    import uvicorn
    config = uvicorn.Config(phone.public_app, host="127.0.0.1", port=PHONE_PORT, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # the main server owns signals
    _phone_server = asyncio.create_task(server.serve())


async def _ensure_phone() -> None:
    if not phone.configured():
        if tunnel.proc:
            tunnel.stop()
        phone.STATE.update(public_url=None, webhooks=None,
                           error=None if not phone.cfg().get("enabled") else "Fill in all Phone settings to go online.")
        return
    await _start_phone_server()
    if not (tunnel.proc and tunnel.proc.poll() is None):
        binary = cloudflared_bin()
        if not binary:
            phone.STATE["error"] = "cloudflared isn't installed. Run the JARVIS installer again (or: brew install cloudflared)."
            return
        (LOG_DIR / "tunnel.out").write_text("")
        phone.STATE.update(public_url=None, webhooks=None)
        tunnel.spawn([binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PHONE_PORT}"])
        return
    if not phone.STATE["public_url"]:
        m = _TUNNEL_RE.search((LOG_DIR / "tunnel.out").read_text(errors="replace"))
        if not m:
            if time.time() - tunnel._last_start > 45:
                phone.STATE["error"] = "The internet tunnel didn't come up. Check your connection; retrying."
                tunnel.stop()
            return
        phone.STATE.update(public_url=m.group(0), error=None)
        tunnel.state = "running"
    if phone.STATE["configured_for"] != phone.STATE["public_url"]:
        try:
            await phone.configure_webhooks(phone.STATE["public_url"])
        except Exception as e:
            phone.STATE.update(error=str(e), webhooks="failed")


async def restart_phone() -> None:
    tunnel.stop()
    phone.STATE.update(public_url=None, webhooks=None, configured_for=None, error=None)
    await _ensure_phone()


async def supervise(interval: float = 4.0) -> None:
    while True:
        for fn in (_ensure_agent, _ensure_gateway, _ensure_phone):
            try:
                await fn()
            except Exception:
                log.exception("supervisor step failed")
        await asyncio.sleep(interval)


def start() -> None:
    global _task
    if os.getenv("JARVIS_NO_SUPERVISOR") == "1":
        return
    _task = asyncio.create_task(supervise())


def stop_all() -> None:
    if _task:
        _task.cancel()
    agent.stop()
    gateway.stop()
    tunnel.stop()
    if _phone_server:
        _phone_server.cancel()


async def restart_gateway() -> None:
    gateway.stop()
    gateway.restarts = 0
    gateway.state = "stopped"
    await _ensure_gateway()
