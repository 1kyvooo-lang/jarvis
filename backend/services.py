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
        path = LOG_DIR / f"{self.name}.out"
        try:   # keep helper logs from growing forever
            if path.stat().st_size > 5_000_000:
                path.replace(path.with_suffix(".out.1"))
        except OSError:
            pass
        self._log = open(path, "ab")
        self.proc = subprocess.Popen(argv, cwd=str(ROOT), stdout=self._log, stderr=subprocess.STDOUT,
                                     env={**os.environ, **(env or {})}, start_new_session=True)
        try:
            PID_DIR.mkdir(parents=True, exist_ok=True)
            (PID_DIR / f"{self.name}.pid").write_text(str(self.proc.pid))
        except OSError:
            pass
        self._last_start = time.time()
        self.state = "starting"
        log.info("started %s (pid %s)", self.name, self.proc.pid)

    def stop(self) -> None:
        (PID_DIR / f"{self.name}.pid").unlink(missing_ok=True)
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


PID_DIR = LOG_DIR.parent / "pids"


def cleanup_orphans() -> list[str]:
    """Stop helpers left running by a previous JARVIS (e.g. after an update or a crash), so every
    start gets fresh ones running the current code. Only processes we started are touched."""
    import psutil
    killed = []
    if not PID_DIR.exists():
        return killed
    marks = {"agent": "agent.server", "hermes": "gateway", "hermes-public": "gateway", "tunnel": "cloudflared"}
    for f in PID_DIR.glob("*.pid"):
        name = f.stem
        try:
            pr = psutil.Process(int(f.read_text().strip()))
            cmd = " ".join(pr.cmdline())
            if marks.get(name, "\0") in cmd:
                pr.terminate()
                try:
                    pr.wait(6)
                except psutil.TimeoutExpired:
                    pr.kill()
                killed.append(name)
        except (ValueError, OSError, psutil.Error):
            pass
        f.unlink(missing_ok=True)
    if killed:
        log.info("stopped leftover helpers: %s", ", ".join(killed))
    return killed


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


# ---------------------------------------------------------------- receptionist brain (separate Hermes profile)

PUBLIC_HERMES_PORT = int(os.getenv("JARVIS_PUBLIC_HERMES_PORT", "8643"))
public_gateway = Service("hermes-public", f"http://127.0.0.1:{PUBLIC_HERMES_PORT}/health")


def public_needed() -> bool:
    from . import google
    r = db.get_settings().get("receptionist") or {}
    return bool((r.get("answer_others") and phone.configured()) or (r.get("inbox_assistant") and google.connected()))


_force_ok: dict[str, bool] = {}


def _supports_force(binary: str) -> bool:
    if binary not in _force_ok:
        try:
            out = subprocess.run([binary, "gateway", "run", "--help"], capture_output=True, text=True, timeout=30)
            _force_ok[binary] = "--force" in (out.stdout + out.stderr)
        except Exception:
            _force_ok[binary] = False
    return _force_ok[binary]


async def _ensure_public() -> None:
    from shared.settings import private_token
    if not public_needed():
        if public_gateway.proc:
            public_gateway.stop()
        public_gateway.state, public_gateway.detail = "stopped", "not needed"
        return
    key = private_token("hermes_public_api_key")
    client = hermes.HermesClient(url=f"http://127.0.0.1:{PUBLIC_HERMES_PORT}", key=key)
    if public_gateway.proc and public_gateway.proc.poll() is None:
        h = await client.health()
        public_gateway.state = "running" if h["authorized"] else "starting"
        public_gateway.detail = h["error"] or ""
        return
    binary = hermes_bin()
    if not binary:
        public_gateway.state = "unavailable"
        return
    if public_gateway.proc and public_gateway.proc.poll() is not None:
        public_gateway.restarts += 1
        public_gateway.detail = "Receptionist stopped unexpectedly:\n" + _tail(LOG_DIR / "hermes-public.out")
        if time.time() - public_gateway._last_start < 10 * min(public_gateway.restarts, 6):
            public_gateway.state = "failed"
            return
    home = hermes.public_home()
    try:
        hermes.ensure_public_config(home)
        hermes.ensure_env(home=home, key=key, port=PUBLIC_HERMES_PORT)
    except Exception as e:
        log.warning("couldn't write receptionist config: %s", e)
        return
    argv = [binary, "gateway", "run"]
    if _supports_force(binary):   # it has no chat platforms, so it can't double-bind anything
        argv.append("--force")
    public_gateway.spawn(argv, env={
        "HERMES_HOME": str(home), "API_SERVER_ENABLED": "true", "API_SERVER_KEY": key,
        "API_SERVER_HOST": "127.0.0.1", "API_SERVER_PORT": str(PUBLIC_HERMES_PORT)})


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
        for fn in (_ensure_agent, _ensure_gateway, _ensure_phone, _ensure_public):
            try:
                await fn()
            except Exception:
                log.exception("supervisor step failed")
        await asyncio.sleep(interval)


def start() -> None:
    global _task
    if os.getenv("JARVIS_NO_SUPERVISOR") == "1":
        return
    try:
        cleanup_orphans()
    except Exception:
        log.exception("orphan cleanup failed")
    _task = asyncio.create_task(supervise())


def stop_all() -> None:
    if _task:
        _task.cancel()
    agent.stop()
    gateway.stop()
    public_gateway.stop()
    tunnel.stop()
    if _phone_server:
        _phone_server.cancel()


async def restart_gateway() -> None:
    gateway.stop()
    gateway.restarts = 0
    gateway.state = "stopped"
    await _ensure_gateway()


async def restart_all() -> None:
    """Fresh helpers: stop the Mac agent, both Hermes gateways and the tunnel, then start again."""
    for svc in (agent, gateway, public_gateway, tunnel):
        svc.stop()
        svc.restarts = 0
        svc.state = "stopped"
    cleanup_orphans()
    phone.STATE.update(public_url=None, webhooks=None, configured_for=None)
    for fn in (_ensure_agent, _ensure_gateway, _ensure_phone, _ensure_public):
        try:
            await fn()
        except Exception:
            log.exception("restart step failed")
