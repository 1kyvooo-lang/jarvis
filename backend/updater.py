"""One-click updates from GitHub.

check(): compares the installed version (data/version, a commit SHA) with the latest commit on the repo's main branch.
apply(): downloads that commit's source, then runs its scripts/update.sh detached. The script copies the code in,
refreshes packages and the dashboard, and restarts JARVIS. Settings, history, keys and memory stay where they are.
"""
import io
import os
import subprocess
import tarfile
import time
from pathlib import Path

import httpx

from shared.settings import DATA_DIR, LOG_DIR, ROOT

REPO = os.environ.get("JARVIS_UPDATE_REPO", "1kyvooo-lang/jarvis")
BRANCH = os.environ.get("JARVIS_UPDATE_BRANCH", "main")
VERSION_FILE = DATA_DIR / "version"
WORK = DATA_DIR / "update"
STATE: dict = {"checked_at": None, "latest": None, "error": None, "running": False}
_transport: httpx.AsyncBaseTransport | None = None  # tests inject a mock


def _read_release() -> str | None:
    try:
        return (ROOT / ".release").read_text().strip() or None
    except OSError:
        return None


LOADED = _read_release()     # the code version this process is actually running


def stale() -> bool:
    """True when newer code is on disk than what's running (e.g. an update whose restart didn't happen)."""
    disk = _read_release()
    return bool(disk and LOADED and disk != LOADED)


def restart_detached() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["/bin/bash", str(ROOT / "scripts" / "restart.sh")], cwd=str(ROOT), start_new_session=True,
                     stdout=open(LOG_DIR / "restart.log", "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def auto_enabled() -> bool:
    from . import db
    return bool((db.get_settings().get("update") or {}).get("auto", True))


def current() -> str | None:
    for p in (VERSION_FILE, ROOT / ".release"):
        try:
            v = p.read_text().strip()
            if v:
                return v
        except OSError:
            pass
    return None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60, follow_redirects=True, transport=_transport,
                             headers={"User-Agent": "JARVIS-updater", "Accept": "application/vnd.github+json"})


def info() -> dict:
    latest = STATE["latest"]
    cur = current()
    log = LOG_DIR / "update.log"
    last_error = None
    try:
        tail = log.read_text().strip().splitlines()[-3:]
        if tail and tail[-1].startswith("FAILED"):
            last_error = tail[-1]
    except OSError:
        pass
    return {
        "repo": REPO, "current": cur, "latest": latest, "running_version": LOADED, "auto": auto_enabled(),
        "available": bool(latest and latest["sha"] != cur),
        "checked_at": STATE["checked_at"], "error": STATE["error"] or last_error,
        "running": STATE["running"],
    }


async def check() -> dict:
    try:
        async with _client() as c:
            r = await c.get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}")
        if r.status_code == 404:
            raise RuntimeError(f"Update source github.com/{REPO} wasn't found.")
        r.raise_for_status()
        j = r.json()
        STATE["latest"] = {"sha": j["sha"], "message": (j.get("commit", {}).get("message") or "").split("\n")[0][:200],
                           "date": j.get("commit", {}).get("committer", {}).get("date")}
        STATE["error"] = None
    except Exception as e:  # network down, rate-limited, …
        STATE["error"] = f"Couldn't check for updates: {e}"
    STATE["checked_at"] = time.time()
    return info()


def _safe_extract(data: bytes, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        try:
            t.extractall(dest, filter="data")
        except TypeError:  # Python without extraction filters
            for m in t.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts or m.issym() or m.islnk():
                    raise RuntimeError("Unsafe path in the update archive.")
            t.extractall(dest)
    dirs = [p for p in dest.iterdir() if p.is_dir()]
    if len(dirs) != 1 or not (dirs[0] / "scripts" / "update.sh").exists():
        raise RuntimeError("The downloaded update doesn't look like JARVIS.")
    return dirs[0]


async def apply() -> dict:
    if STATE["running"]:
        return info()
    await check()
    latest = STATE["latest"]
    if not latest:
        raise RuntimeError(STATE["error"] or "Couldn't find the latest version.")
    sha = latest["sha"]
    async with _client() as c:
        r = await c.get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}")
    r.raise_for_status()
    import shutil
    shutil.rmtree(WORK, ignore_errors=True)
    src = _safe_extract(r.content, WORK)
    (src / ".release").write_text(sha)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "update.log", "w")
    # Detached: the script restarts JARVIS (this process) when it's done.
    subprocess.Popen(["/bin/bash", str(src / "scripts" / "update.sh"), str(src), str(ROOT), sha],
                     cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    STATE["running"] = True
    return info()
