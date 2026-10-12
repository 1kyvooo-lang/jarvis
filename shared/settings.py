"""Paths, environment and shared secrets used by both the backend and the agent."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(ROOT / "data"))).expanduser()
LOG_DIR = DATA_DIR / "logs"
CONFIG_DIR = ROOT / "config"
PERMISSIONS_PATH = Path(os.getenv("JARVIS_PERMISSIONS_FILE", str(CONFIG_DIR / "permissions.json"))).expanduser()
PERMISSIONS_EXAMPLE = CONFIG_DIR / "permissions.example.json"

BACKEND_HOST = os.getenv("JARVIS_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("JARVIS_BACKEND_PORT", "8000"))
AGENT_HOST = os.getenv("JARVIS_AGENT_HOST", "127.0.0.1")
AGENT_PORT = int(os.getenv("JARVIS_AGENT_PORT", "8765"))
AGENT_URL = os.getenv("JARVIS_AGENT_URL", f"http://{AGENT_HOST}:{AGENT_PORT}")
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
HERMES_PORT = int(os.getenv("JARVIS_HERMES_PORT", "8642"))
HERMES_URL = os.getenv("JARVIS_HERMES_URL", f"http://127.0.0.1:{HERMES_PORT}")

for d in (DATA_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _write_private(path: Path, value: str) -> None:
    path.write_text(value)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def private_token(name: str) -> str:
    """A random secret generated once into data/<name> (0600)."""
    path = DATA_DIR / name
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    _write_private(path, token)
    return token


def agent_token() -> str:
    """Shared secret for backend <-> agent auth.

    Uses JARVIS_AGENT_TOKEN if set, otherwise a random token generated once into
    data/agent_token (permissions 0600) so both local processes can read it.
    """
    env = os.getenv("JARVIS_AGENT_TOKEN", "").strip()
    if env and env != "change-me":
        return env
    path = DATA_DIR / "agent_token"
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    _write_private(path, token)
    return token


def ensure_permissions_file() -> Path:
    """Create config/permissions.json from the example on first run (never overwrites)."""
    if not PERMISSIONS_PATH.exists():
        PERMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PERMISSIONS_EXAMPLE, PERMISSIONS_PATH)
    return PERMISSIONS_PATH


_perm_cache: dict = {"mtime": None, "data": None}


def load_permissions() -> dict:
    """Read permissions.json, re-reading only when the file changed."""
    path = ensure_permissions_file()
    mtime = path.stat().st_mtime
    if _perm_cache["mtime"] != mtime:
        data = json.loads(path.read_text())
        data.setdefault("approved_apps", [])
        data.setdefault("approved_domains", [])
        data.setdefault("approved_directories", [])
        data.setdefault("approval_required", [])
        data.setdefault("disabled_tools", [])
        b = data.setdefault("browser", {})
        b.setdefault("ask_outside_approved_domains", True)
        b.setdefault("always_ask", ["browser_fill_form", "browser_file_upload", "browser_drop", "browser_evaluate",
                                    "browser_run_code_unsafe", "browser_handle_dialog"])
        b.setdefault("risky_words", ["buy", "purchase", "pay", "checkout", "order", "submit", "send", "post", "delete",
                                     "confirm", "subscribe", "sign up", "transfer", "book"])
        if _migrate_permissions(data):
            save_permissions(data)
            mtime = path.stat().st_mtime
        _perm_cache.update(mtime=mtime, data=data)
    return json.loads(json.dumps(_perm_cache["data"]))  # defensive copy


def _migrate_permissions(data: dict) -> bool:
    """One-time additions for new features. Each runs once, so the user's later edits stick."""
    done = data.setdefault("migrations", [])
    changed = False
    if "media-apps-2026-10" not in done:
        for app in ["Spotify", "Music", "Mail", "Safari", "Google Chrome", "Calendar", "Notes", "Messages",
                    "FaceTime", "Photos", "Finder", "Reminders"]:
            if app.lower() not in {a.lower() for a in data["approved_apps"]}:
                data["approved_apps"].append(app)
        for d in ["youtube.com", "spotify.com", "music.apple.com", "google.com"]:
            if d not in data["approved_domains"]:
                data["approved_domains"].append(d)
        # Opening an app from the approved list no longer needs a click.
        data["approval_required"] = [t for t in data["approval_required"] if t != "open_app"]
        done.append("media-apps-2026-10")
        changed = True
    return changed


def save_permissions(data: dict) -> None:
    path = ensure_permissions_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
    _perm_cache["mtime"] = None
