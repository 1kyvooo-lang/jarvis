"""The `jarvis` MCP server that Hermes Agent connects to (stdio).

It exposes:
  • JARVIS's Mac tools (apps, files in approved folders, system info, notifications),
    tasks/automations and dashboard memory — executed through the JARVIS backend, so
    allowlists, approvals, the emergency stop and the activity log all apply;
  • Playwright MCP's browser tools, proxied: every call is checked by the backend's
    browser policy first, and consequential ones wait for your Approve click.

Hermes launches this as: <jarvis>/.venv/bin/python -m jarvis_mcp.server
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
from contextlib import AsyncExitStack
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from shared.settings import BACKEND_URL, DATA_DIR, LOG_DIR, ROOT, agent_token

# stdout is the MCP channel — log to a file only.
log = logging.getLogger("jarvis.mcp")
_h = RotatingFileHandler(LOG_DIR / "mcp.log", maxBytes=1_000_000, backupCount=2)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_h)
log.setLevel(logging.INFO)

PAGE_URL_RE = re.compile(r"Page URL:\s*(\S+)")
BROWSER_NOTE = {
    "ask": " (Consequential uses wait for the user's approval in the JARVIS dashboard.)",
}


def _backend() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BACKEND_URL, timeout=httpx.Timeout(10, read=330),
                             headers={"Authorization": f"Bearer {agent_token()}"})


def playwright_command() -> StdioServerParameters | None:
    """Playwright MCP from JARVIS's own install (mcp-runtime/), with a persistent profile."""
    cli = ROOT / "mcp-runtime" / "node_modules" / "@playwright" / "mcp" / "cli.js"
    node = os.getenv("JARVIS_NODE") or shutil.which("node") or "/opt/homebrew/bin/node"
    if not cli.exists() or not Path(node).exists():
        log.warning("Playwright MCP not available (cli=%s node=%s)", cli.exists(), node)
        return None
    args = [str(cli), "--user-data-dir", str(DATA_DIR / "browser-profile"), "--output-dir", str(DATA_DIR / "browser-output")]
    exe = os.getenv("JARVIS_CHROMIUM_PATH")
    if exe:
        args += ["--executable-path", exe]
    else:
        chrome = Path("/Applications/Google Chrome.app")
        args += ["--browser", "chrome" if chrome.exists() else "chromium"]
    settings_file = DATA_DIR / "browser_settings.json"
    headless = os.getenv("JARVIS_BROWSER_HEADLESS") == "1"
    if settings_file.exists():
        try:
            headless = bool(json.loads(settings_file.read_text()).get("headless", headless))
        except ValueError:
            pass
    if headless:
        args.append("--headless")
    args += json.loads(os.getenv("JARVIS_PLAYWRIGHT_EXTRA_ARGS", "[]"))
    return StdioServerParameters(command=node, args=args, env={**os.environ})


class BrowserProxy:
    def __init__(self):
        self.stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.tools: list[types.Tool] = []
        self.page_url: str | None = None
        self.error: str | None = None

    async def start(self) -> None:
        params = playwright_command()
        if not params:
            self.error = "Playwright MCP isn't installed (run the JARVIS installer)."
            return
        try:
            read, write = await self.stack.enter_async_context(stdio_client(params))
            self.session = await self.stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
            self.tools = (await self.session.list_tools()).tools
            log.info("Playwright MCP ready with %d tools", len(self.tools))
        except Exception as e:
            self.error = f"Playwright MCP failed to start: {e}"
            log.exception("playwright start failed")

    async def close(self) -> None:
        await self.stack.aclose()

    def names(self) -> set[str]:
        return {t.name for t in self.tools}

    async def call(self, name: str, args: dict) -> list:
        assert self.session
        async with _backend() as c:
            r = await c.post("/api/internal/authorize", json={"tool": name, "args": args, "page_url": self.page_url})
            r.raise_for_status()
            verdict = r.json()
        if verdict["decision"] != "allow":
            raise RuntimeError(verdict["reason"])
        result = await self.session.call_tool(name, args)
        texts = [c.text for c in result.content if isinstance(c, types.TextContent)]
        joined = "\n".join(texts)
        m = PAGE_URL_RE.search(joined)
        if m:
            self.page_url = m.group(1)
        elif name == "browser_navigate":
            self.page_url = args.get("url")
        async with _backend() as c:
            await c.post("/api/internal/report", json={
                "tool": name, "args": args, "ok": not result.isError, "summary": joined[:1500],
                "approval_id": verdict.get("approval_id")})
        if result.isError:
            raise RuntimeError(joined or "browser action failed")
        return list(result.content)


browser = BrowserProxy()
server = Server("jarvis", instructions=(
    "Tools for acting on the user's Mac and web browser on behalf of JARVIS. Calls that need the user's OK "
    "block until they click Approve or Deny in the JARVIS dashboard."))


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    tools: list[types.Tool] = []
    try:
        async with _backend() as c:
            r = await c.get("/api/internal/tools")
            r.raise_for_status()
            for t in r.json()["tools"]:
                tools.append(types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"]))
    except httpx.HTTPError as e:
        log.warning("backend unavailable for tool list: %s", e)
    for t in browser.tools:
        read_only = bool(t.annotations and t.annotations.readOnlyHint)
        tools.append(types.Tool(name=t.name, description=(t.description or "") + ("" if read_only else BROWSER_NOTE["ask"]),
                                inputSchema=t.inputSchema, annotations=t.annotations))
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    arguments = arguments or {}
    if name in browser.names():
        return await browser.call(name, arguments)
    async with _backend() as c:
        r = await c.post("/api/internal/run", json={"tool": name, "args": arguments})
        r.raise_for_status()
        res = r.json()
    if res["status"] == "ok":
        return [types.TextContent(type="text", text=json.dumps(res.get("output"), default=str)[:50_000])]
    if res["status"] == "pending_approval":
        return [types.TextContent(type="text", text=f"Waiting for the user's approval (#{res.get('approval_id')}).")]
    raise RuntimeError(res.get("error") or "failed")


async def main() -> None:
    log.info("jarvis MCP server starting (pid %s)", os.getpid())
    await browser.start()
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await browser.close()
        log.info("jarvis MCP server stopped")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    asyncio.run(main())
