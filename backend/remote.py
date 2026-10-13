"""JARVIS on your phone, privately.

Uses Tailscale (free): a private network between *your own* devices. `tailscale serve`
publishes this Mac's dashboard at https://<your-mac>.<tailnet>.ts.net, reachable only from
devices signed in to your Tailscale account — never the public internet. On top of that,
every request that doesn't come from this Mac itself needs your passcode (a signed,
HttpOnly cookie after you log in once; repeated wrong guesses are locked out).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import time

from shared.settings import BACKEND_PORT, private_token

from . import db

COOKIE = "jarvis_remote"
SESSION_DAYS = 30
_fails: dict[str, list[float]] = {}


# ---------------------------------------------------------------- who is asking

def is_remote(headers, client_host: str | None = None) -> bool:
    """True for requests relayed from another device. JARVIS only listens on 127.0.0.1, so the only
    way in from elsewhere is a local proxy (tailscale serve), which always adds forwarding headers."""
    keys = {k.lower() for k in headers.keys()}
    return bool(keys & {"x-forwarded-for", "forwarded", "x-forwarded-host"}) or any(k.startswith("tailscale-") for k in keys)


def _secret() -> bytes:
    return private_token("remote_session_secret").encode()


def make_session() -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    sig = hmac.new(_secret(), f"v1.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"v1.{exp}.{sig}"


def valid_session(value: str | None) -> bool:
    try:
        v, exp, sig = (value or "").split(".")
        good = hmac.new(_secret(), f"{v}.{exp}".encode(), hashlib.sha256).hexdigest()
        return v == "v1" and int(exp) > time.time() and hmac.compare_digest(sig, good)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- passcode

def settings() -> dict:
    return dict(db.get_settings().get("remote") or {})


def has_passcode() -> bool:
    return bool(settings().get("hash"))


def set_passcode(code: str) -> None:
    code = code.strip()
    if len(code) < 6:
        raise ValueError("Use at least 6 characters.")
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), 300_000).hex()
    db.set_setting("remote", {**settings(), "hash": h, "salt": salt})
    # changing the passcode signs out every phone
    from shared.settings import DATA_DIR
    (DATA_DIR / "remote_session_secret").unlink(missing_ok=True)


def check_passcode(code: str, who: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(who, []) if now - t < 900]
    if len(recent) >= 5:
        raise PermissionError("Too many wrong tries. Wait 15 minutes.")
    s = settings()
    if not s.get("hash"):
        raise PermissionError("Set a passcode on the Mac first (Settings → Phone access).")
    h = hashlib.pbkdf2_hmac("sha256", code.strip().encode(), bytes.fromhex(s["salt"]), 300_000).hex()
    if hmac.compare_digest(h, s["hash"]):
        _fails.pop(who, None)
        return True
    _fails[who] = recent + [now]
    return False


# ---------------------------------------------------------------- Tailscale

def tailscale_bin() -> str | None:
    for c in (os.getenv("JARVIS_TAILSCALE"), "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
              shutil.which("tailscale"), "/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale"):
        if c and os.path.exists(c):
            return c
    return None


def _ts(*args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    b = tailscale_bin()
    if not b:
        raise RuntimeError("Tailscale isn't installed on this Mac.")
    return subprocess.run([b, *args], capture_output=True, text=True, timeout=timeout)


def status() -> dict:
    out = {"installed": bool(tailscale_bin()), "running": False, "url": None, "serving": False,
           "passcode": has_passcode(), "error": None}
    if not out["installed"]:
        return out
    try:
        st = json.loads(_ts("status", "--json").stdout or "{}")
        out["running"] = st.get("BackendState") == "Running"
        dns = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if dns:
            out["url"] = f"https://{dns}"
        sv = _ts("serve", "status", "--json")
        out["serving"] = f"127.0.0.1:{BACKEND_PORT}" in (sv.stdout or "") or f"localhost:{BACKEND_PORT}" in (sv.stdout or "")
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def enable() -> dict:
    if not has_passcode():
        raise ValueError("Set a passcode first.")
    target = f"http://127.0.0.1:{BACKEND_PORT}"
    errors = []
    for args in (["serve", "--bg", "--yes", target], ["serve", "--bg", target], ["serve", "--bg", "--https=443", target]):
        r = _ts(*args, timeout=40)
        if r.returncode == 0:
            break
        errors.append((r.stderr or r.stdout).strip())
    else:
        msg = errors[-1] if errors else "unknown error"
        if "https" in msg.lower() and "enable" in msg.lower():
            msg = "Turn on HTTPS for your tailnet first (Tailscale admin → DNS → enable MagicDNS and HTTPS certificates). " + msg
        raise RuntimeError(msg[:400])
    db.log_activity("Phone access turned on (Tailscale)", "info", tool="remote", source="user")
    return status()


def disable() -> dict:
    for args in (["serve", "--https=443", "off"], ["serve", "reset"]):
        if _ts(*args).returncode == 0:
            break
    db.log_activity("Phone access turned off", "info", tool="remote", source="user")
    return status()
