"""The `jarvis_public` MCP server for the receptionist profile (stdio).

It exposes ONLY the receptionist tools (availability, booking, messages, email sorting and
reply drafts), each pinned to one caller by a ticket. It authenticates to the backend with
its own token, which the backend accepts for these endpoints only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from shared.settings import BACKEND_URL, LOG_DIR, ROOT, private_token

log = logging.getLogger("jarvis.mcp.public")
_h = RotatingFileHandler(LOG_DIR / "mcp-public.log", maxBytes=500_000, backupCount=1)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_h)
log.setLevel(logging.INFO)

server = Server("jarvis_public", instructions="Receptionist tools: availability, booking, messages and email triage.")


def _backend() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BACKEND_URL, timeout=60,
                             headers={"Authorization": f"Bearer {private_token('public_mcp_token')}"})


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    try:
        async with _backend() as c:
            r = await c.get("/api/internal/public/tools")
            r.raise_for_status()
            return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
                    for t in r.json()["tools"]]
    except httpx.HTTPError as e:
        log.warning("backend unavailable: %s", e)
        return []


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    async with _backend() as c:
        r = await c.post("/api/internal/public/run", json={"tool": name, "args": arguments or {}})
        r.raise_for_status()
        res = r.json()
    if res["status"] == "ok":
        return [types.TextContent(type="text", text=json.dumps(res.get("output"), default=str)[:20_000])]
    raise RuntimeError(res.get("error") or "failed")


async def main() -> None:
    log.info("jarvis_public MCP server starting (pid %s)", os.getpid())
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    asyncio.run(main())
