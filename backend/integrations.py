"""Interfaces for future integrations. Nothing here pretends to work: each
provider reports its real status, and only implemented ones are 'available'."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class Integration(Protocol):
    key: str
    name: str

    def status(self) -> dict: ...


@dataclass
class Placeholder:
    key: str
    name: str
    env_vars: tuple[str, ...]
    note: str

    def status(self) -> dict:
        configured = all(os.getenv(v) for v in self.env_vars) if self.env_vars else False
        return {"key": self.key, "name": self.name, "state": "configured — not implemented yet" if configured
                else "awaiting configuration", "implemented": False, "env_vars": list(self.env_vars), "note": self.note}


@dataclass
class Implemented:
    key: str
    name: str
    note: str

    def status(self) -> dict:
        return {"key": self.key, "name": self.name, "state": "available", "implemented": True, "env_vars": [], "note": self.note}


INTEGRATIONS: list = [
    Implemented("hermes", "Hermes Agent (brain)", "Plans, remembers and uses tools; model chosen in Hermes."),
    Implemented("elevenlabs", "ElevenLabs voice", "Scribe speech-to-text and natural text-to-speech."),
    Implemented("playwright", "Playwright MCP browser", "Reads pages freely; consequential actions ask first."),
    Implemented("mac_agent", "Mac agent", "Apps, files in approved folders, system info, notifications."),
    Implemented("telephony", "Phone calls & SMS (Twilio)", "Call or text JARVIS from your phone; he can call or text you. Settings → Phone."),
    Placeholder("calendar", "Calendar (Google / iCloud)", ("GOOGLE_CLIENT_ID",), "Hermes skills or an MCP server can add this."),
    Placeholder("email", "Email", ("GOOGLE_CLIENT_ID",), "Sending email will always require approval."),
    Placeholder("smart_home", "Smart home (HomeKit / Home Assistant)", ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN"), ""),
    Placeholder("market_data", "Market data / trading dashboards", ("MARKET_DATA_API_KEY",), "Read-only quotes first; no order placement."),
    Placeholder("messaging", "Telegram / Discord / Slack", (), "Hermes supports these itself (`hermes gateway setup`)."),
]


def all_status() -> list[dict]:
    return [i.status() for i in INTEGRATIONS]
