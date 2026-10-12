"""Long-term memory: explicit saved memories + retrieval of relevant ones per turn."""
from __future__ import annotations

import re

from . import db

KINDS = ("preference", "fact", "project", "goal", "instruction")
ALWAYS_INCLUDE = ("preference", "instruction")

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),                 # Anthropic/OpenAI style keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                    # AWS
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),          # GitHub
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),           # Slack
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|passcode|pin|api[_ -]?key|secret|token|2fa|otp)\b\s*(is|:|=)\s*\S+"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),                  # card-like numbers
]


class SecretRejected(ValueError):
    pass


def looks_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def create(kind: str, content: str, source: str = "user") -> dict:
    content = content.strip()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not content:
        raise ValueError("content is empty")
    if looks_secret(content):
        raise SecretRejected("This looks like a password, key or other secret, so it was not saved to memory.")
    t = db.now()
    cur = db.ex("INSERT INTO memories(kind, content, source, created_at, updated_at) VALUES (?,?,?,?,?)",
                (kind, content[:4000], source, t, t))
    return db.one("SELECT * FROM memories WHERE id=?", (cur.lastrowid,))


def update(mid: int, kind: str | None, content: str | None) -> dict | None:
    row = db.one("SELECT * FROM memories WHERE id=?", (mid,))
    if not row:
        return None
    kind = kind or row["kind"]
    content = (content if content is not None else row["content"]).strip()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if looks_secret(content):
        raise SecretRejected("This looks like a secret, so it was not saved.")
    db.ex("UPDATE memories SET kind=?, content=?, updated_at=? WHERE id=?", (kind, content, db.now(), mid))
    return db.one("SELECT * FROM memories WHERE id=?", (mid,))


def search(query: str = "", kind: str | None = None, limit: int = 200) -> list[dict]:
    params: list = []
    if query.strip():
        if db.FTS_OK:
            terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1][:12]
            if not terms:
                return []
            match = " OR ".join(f'"{t}"*' for t in terms)
            sql = ("SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ?")
            params.append(match)
            if kind:
                sql += " AND m.kind=?"
                params.append(kind)
            sql += " ORDER BY bm25(memories_fts) LIMIT ?"
            params.append(limit)
            return db.q(sql, params)
        sql, params = "SELECT * FROM memories WHERE content LIKE ?", [f"%{query}%"]
    else:
        sql = "SELECT * FROM memories WHERE 1=1"
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    return db.q(sql, params)


def relevant_context(user_text: str, max_items: int = 12) -> list[dict]:
    """Preferences/instructions always, plus the best keyword matches for this message."""
    seen, out = set(), []
    for r in db.q(f"SELECT * FROM memories WHERE kind IN ({','.join('?' * len(ALWAYS_INCLUDE))}) "
                  "ORDER BY updated_at DESC LIMIT ?", (*ALWAYS_INCLUDE, max_items)):
        seen.add(r["id"]); out.append(r)
    for r in search(user_text, limit=max_items):
        if r["id"] not in seen and len(out) < max_items * 2:
            seen.add(r["id"]); out.append(r)
    return out
