"""Privacy guard: strips secrets out of text before it goes to a cloud AI model.

Catches API keys and tokens (Anthropic, OpenAI, Google, AWS, GitHub, Slack, Stripe,
Twilio, ElevenLabs-style hex keys, JWTs), private-key blocks, "password: …" style
assignments, payment card numbers (Luhn-checked) and one-time codes in messages like
"your code is 123456". Each is replaced with a [REDACTED …] marker.
"""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("API key", re.compile(r"\bsk-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_\-]{20,}")),
    ("API key", re.compile(r"\b(?:AIza[0-9A-Za-z_\-]{35}|GOCSPX-[0-9A-Za-z_\-]{20,})")),
    ("access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("API key", re.compile(r"\b(?:rk|pk|sk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("token", re.compile(r"\b(?:SK|AC)[0-9a-f]{32}\b(?=.*(?:secret|token|auth))", re.I)),
    ("password", re.compile(r"(?i)\b(pass(?:word|wd|code)?|pwd|secret|api[_ -]?key|auth[_ -]?token|access[_ -]?token)"
                            r"(\s*(?:is|=|:)\s*)(\"[^\"]{4,}\"|'[^']{4,}'|[^\s,;]{4,})")),
    ("one-time code", re.compile(r"(?i)\b(code|otp|verification|passcode|pin)\b([^0-9\n]{0,25})\b(\d{4,8})\b")),
    ("hex secret", re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{32,64}\b")),
]
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact(text: str, ids_ok: bool = False) -> tuple[str, int]:
    """Return (safe text, number of secrets removed). ids_ok skips the bare-hex rule, for tool
    results that legitimately contain long hex ids."""
    if not text:
        return text, 0
    count = 0

    def sub(kind):
        def f(m: re.Match) -> str:
            nonlocal count
            count += 1
            if kind == "password":
                return f"{m.group(1)}{m.group(2)}[REDACTED password]"
            if kind == "one-time code":
                return f"{m.group(1)}{m.group(2)}[REDACTED code]"
            return f"[REDACTED {kind}]"
        return f

    for kind, pat in PATTERNS:
        if ids_ok and kind == "hex secret":
            continue
        text = pat.sub(sub(kind), text)

    def card(m: re.Match) -> str:
        nonlocal count
        if _luhn(m.group(0)):
            count += 1
            return "[REDACTED card number]"
        return m.group(0)
    if not ids_ok:      # long numeric ids in tool results could look like card numbers
        text = CARD.sub(card, text)
    return text, count


def redact_obj(obj, ids_ok: bool = True):
    """Redact inside any JSON-able value; returns (value, count)."""
    import json
    raw = json.dumps(obj, default=str)
    safe, n = redact(raw, ids_ok=ids_ok)
    if not n:
        return obj, 0
    try:
        return json.loads(safe), n
    except ValueError:
        return safe, n
