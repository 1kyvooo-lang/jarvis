"""Thin SQLite data layer. All SQL lives here or in migrations/, so moving to
PostgreSQL means changing this module only."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from shared.settings import DATA_DIR

DB_PATH = DATA_DIR / "jarvis.db"
MIGRATIONS = Path(__file__).parent / "migrations"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
FTS_OK = False


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        init()
    return _conn  # type: ignore[return-value]


def init(path: Path | None = None) -> None:
    global _conn, FTS_OK
    with _lock:
        _conn = sqlite3.connect(str(path or DB_PATH), check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)")
        done = {r[0] for r in _conn.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name not in done:
                _conn.executescript(f.read_text())
                _conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (f.name, now()))
        try:  # full-text search for memory retrieval (falls back to LIKE)
            _conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, kind, content='memories', content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
              INSERT INTO memories_fts(rowid, content, kind) VALUES (new.id, new.content, new.kind); END;
            CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, content, kind) VALUES('delete', old.id, old.content, old.kind); END;
            CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, content, kind) VALUES('delete', old.id, old.content, old.kind);
              INSERT INTO memories_fts(rowid, content, kind) VALUES (new.id, new.content, new.kind); END;
            """)
            FTS_OK = True
        except sqlite3.OperationalError:
            FTS_OK = False


def q(sql: str, params: tuple | list = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
    with _lock:
        return conn().execute(sql, params)


# ---------------------------------------------------------------- settings

DEFAULT_SETTINGS: dict[str, Any] = {
    "user_name": "",
    "assistant_name": "JARVIS",
    "voice": {"provider": "elevenlabs", "auto_speak": True, "voice_id": "", "voice_name": "", "tts_model": "",
              "stt_language": "", "browser_voice_name": "", "rate": 1.0},
    "memory": {"auto_retrieve": True, "max_items": 12},
    "hermes": {"api_key": "", "binary": ""},
    "browser": {"headless": False},
    "phone": {"enabled": False, "account_sid": "", "twilio_number": "", "owner_number": "",
              "language": "en-GB", "say_voice": "Polly.Brian", "sms_conversation": ""},
    "google": {"client_id": "", "email": "", "business_hours": {"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"},
               "slot_minutes": 30, "min_notice_hours": 2},
    "receptionist": {"answer_others": True, "business_name": "", "about": "", "booking": True, "appointment_minutes": 30,
                     "inbox_assistant": False, "inbox_minutes": 10, "allow_archive": False, "approve_by_text": True,
                     "labels": ["Needs reply", "Appointments", "Important", "Receipts", "Newsletters", "Other"]},
    "router": {"enabled": False, "auto": True, "routes": {}},
    "briefing": {"enabled": False, "time": "08:00", "days": [1, 2, 3, 4, 5, 6, 7], "via": "text"},
    "update": {"auto": True},
    "wake": {"enabled": True, "threshold": 0.5, "greeting": "Yes? What do you need?", "open_at_login": True},
    "emergency_stop": False,
}


def get_settings() -> dict:
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for r in q("SELECT key, value FROM settings"):
        v = json.loads(r["value"])
        if isinstance(v, dict) and isinstance(out.get(r["key"]), dict):
            out[r["key"]] = {**out[r["key"]], **v}   # new default keys survive older saved settings
        else:
            out[r["key"]] = v
    return out


def set_setting(key: str, value: Any) -> None:
    ex("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, json.dumps(value)))


# ---------------------------------------------------------------- activity

def log_activity(action: str, status: str, tool: str | None = None, approval: str | None = None,
                 result: Any = None, error: str | None = None, source: str = "assistant") -> None:
    res = None if result is None else (result if isinstance(result, str) else json.dumps(result, default=str))
    if res and len(res) > 2000:
        res = res[:2000] + "…"
    ex("INSERT INTO activity(ts, action, tool, status, approval, result, error, source) VALUES (?,?,?,?,?,?,?,?)",
       (now(), action, tool, status, approval, res, error, source))
