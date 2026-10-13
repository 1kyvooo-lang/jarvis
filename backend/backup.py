"""Daily backups of JARVIS's own data: memory, chats, tasks, reminders, settings and permissions.

A consistent snapshot is taken with SQLite's online backup (safe while JARVIS runs), zipped
with permissions.json, and kept for 14 days. If iCloud Drive is on, a copy also goes to
iCloud Drive/JARVIS Backups, so a broken or lost Mac doesn't take your assistant's memory
with it. Keys and tokens live in the macOS Keychain and are never in a backup.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from shared.settings import DATA_DIR, PERMISSIONS_PATH

from . import db

log = logging.getLogger("jarvis.backup")
DIR = DATA_DIR / "backups"
KEEP = 14
ICLOUD = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"


def icloud_dir() -> Path | None:
    return ICLOUD / "JARVIS Backups" if ICLOUD.is_dir() else None


def _prune(folder: Path) -> None:
    files = sorted(folder.glob("jarvis-backup-*.zip"))
    for f in files[:-KEEP]:
        f.unlink(missing_ok=True)


def create(reason: str = "daily") -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = DIR / f"jarvis-backup-{stamp}.zip"
    n = 1
    while out.exists():                       # never overwrite an existing backup
        n += 1
        out = DIR / f"jarvis-backup-{stamp}-{n}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "jarvis.db"
        dst = sqlite3.connect(str(snap))
        with db._lock:
            db.conn().backup(dst)
        dst.close()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "jarvis.db")
            if PERMISSIONS_PATH.exists():
                z.write(PERMISSIONS_PATH, "permissions.json")
            z.writestr("README.txt", f"JARVIS backup ({reason}) made {dt.datetime.now().isoformat(timespec='seconds')}.\n"
                                     "Restore it from JARVIS → Settings → Backups. Keys are not included (they stay in your Keychain).\n")
    _prune(DIR)
    copied = None
    cloud = icloud_dir()
    if cloud and (db.get_settings().get("backup") or {}).get("icloud", True):
        try:
            cloud.mkdir(exist_ok=True)
            shutil.copy2(out, cloud / out.name)
            _prune(cloud)
            copied = str(cloud)
        except OSError as e:
            log.warning("iCloud copy failed: %s", e)
    db.set_setting("backup", {**(db.get_settings().get("backup") or {}), "last": dt.datetime.now().isoformat(timespec="seconds")})
    db.log_activity(f"Backup made ({reason})" + (" and copied to iCloud Drive" if copied else ""), "ok", tool="backup", source="system")
    return {"file": out.name, "size": out.stat().st_size, "icloud": copied}


def listing() -> list[dict]:
    if not DIR.exists():
        return []
    return [{"file": f.name, "size": f.stat().st_size,
             "made": dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes")}
            for f in sorted(DIR.glob("jarvis-backup-*.zip"), reverse=True)]


def restore(name: str) -> dict:
    src = (DIR / name).resolve()
    if not (src.parent == DIR.resolve() and src.name.startswith("jarvis-backup-") and src.suffix == ".zip" and src.exists()):
        raise ValueError("No such backup")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(src) as z:
        z.extract("jarvis.db", tmp)
        create("before restore")                # so a restore can itself be undone
        source = sqlite3.connect(str(Path(tmp) / "jarvis.db"))
        with db._lock:
            source.backup(db.conn())             # replaces the live database in place
        source.close()
        if "permissions.json" in z.namelist():
            data = z.read("permissions.json")
            tmpf = PERMISSIONS_PATH.with_suffix(".restore")
            tmpf.write_bytes(data)
            tmpf.replace(PERMISSIONS_PATH)
    db.log_activity(f"Restored backup {name}", "info", tool="backup", source="user")
    return {"restored": name}


async def loop() -> None:
    """One backup a day (and one shortly after start if the last is older than a day)."""
    await asyncio.sleep(120)
    while True:
        try:
            last = (db.get_settings().get("backup") or {}).get("last")
            age = (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds() if last else 1e9
            if age > 23 * 3600:
                await asyncio.to_thread(create, "daily")
        except Exception:
            log.exception("backup failed")
        await asyncio.sleep(3600)
