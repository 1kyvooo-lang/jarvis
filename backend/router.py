"""LLM router: picks which of your models answers each message.

Routes are Hermes `model_routes` aliases (written into ~/.hermes/config.yaml under
gateway.platforms.api_server.model_routes), so Hermes still does all the work and keeps
its tools and memory; JARVIS only chooses the alias per message.

  • Prefix: start a message with  fast:  think:  vision:  local:  to pick a route yourself.
  • Auto (optional): short, simple messages go to `fast`; long or analytical ones to `think`.
  • Anything else uses your default Hermes model.
"""
from __future__ import annotations

import re

from . import db

ALIASES = ("fast", "think", "vision", "local")
PREFIX = re.compile(r"^\s*(fast|think|deep|vision|local)\s*:\s*", re.I)
HEAVY = re.compile(r"\b(analy[sz]e|plan|strategy|compare|why|explain|design|architecture|debug|research|prove|"
                   r"step[- ]by[- ]step|pros and cons|write (a|an|the) (report|essay|spec|proposal))\b", re.I)


def settings() -> dict:
    r = dict(db.get_settings().get("router") or {})
    r.setdefault("enabled", False)
    r.setdefault("auto", True)
    r.setdefault("routes", {})
    return r


def configured_routes() -> dict[str, dict]:
    r = settings()
    out = {}
    for alias, cfg in (r.get("routes") or {}).items():
        if alias in ALIASES and isinstance(cfg, dict) and (cfg.get("model") or "").strip():
            out[alias] = {k: str(cfg[k]).strip() for k in ("model", "provider", "base_url") if (cfg.get(k) or "").strip()}
    return out


def pick(text: str) -> tuple[str | None, str]:
    """Return (route alias or None for the default model, text with any prefix removed)."""
    m = PREFIX.match(text)
    routes = configured_routes() if settings()["enabled"] else {}
    if m:
        alias = "think" if m.group(1).lower() == "deep" else m.group(1).lower()
        return (alias if alias in routes else None), text[m.end():]
    if not routes or not settings().get("auto"):
        return None, text
    if "think" in routes and (len(text) > 400 or HEAVY.search(text)):
        return "think", text
    if "fast" in routes and len(text) < 80 and "\n" not in text:
        return "fast", text
    return None, text
