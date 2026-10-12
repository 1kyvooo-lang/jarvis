"""Authenticated client for the local Mac agent."""
from __future__ import annotations

import time

import httpx

from shared.settings import AGENT_URL, agent_token

_transport: httpx.AsyncBaseTransport | None = None  # tests inject an ASGI transport here
_tools_cache: dict = {"at": 0.0, "data": None}


def _client(timeout: float = 10) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=AGENT_URL, transport=_transport, timeout=timeout,
                             headers={"Authorization": f"Bearer {agent_token()}"})


async def status() -> dict:
    try:
        async with _client(3) as c:
            r = await c.get("/status")
            if r.status_code == 401:
                return {"online": False, "error": "Agent rejected our token (check JARVIS_AGENT_TOKEN)"}
            r.raise_for_status()
            return {"online": True, **r.json()}
    except httpx.HTTPError as e:
        return {"online": False, "error": f"Agent not reachable at {AGENT_URL} ({type(e).__name__})"}


async def tools(force: bool = False) -> dict | None:
    if not force and _tools_cache["data"] and time.time() - _tools_cache["at"] < 5:
        return _tools_cache["data"]
    try:
        async with _client(5) as c:
            r = await c.get("/tools")
            r.raise_for_status()
            _tools_cache.update(at=time.time(), data=r.json())
            return _tools_cache["data"]
    except httpx.HTTPError:
        _tools_cache.update(at=0.0, data=None)
        return None


async def execute(request_id: str, tool: str, args: dict, approved: bool) -> dict:
    try:
        async with _client(90) as c:
            r = await c.post("/execute", json={"request_id": request_id, "tool": tool, "args": args, "approved": approved})
            if r.status_code == 409:
                return {"ok": False, "error": "This action is already running"}
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Mac agent unavailable: {type(e).__name__}"}


async def control(action: str) -> bool:
    try:
        async with _client(3) as c:
            r = await c.post(f"/control/{action}")
            return r.status_code == 200
    except httpx.HTTPError:
        return False
