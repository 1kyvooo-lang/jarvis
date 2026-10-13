"""Hermes Agent integration: locating it, configuring it for JARVIS, and streaming turns.

Hermes is the brain. JARVIS talks to Hermes's local OpenAI-compatible API server
(`hermes gateway run` with API_SERVER_ENABLED) using the Responses API, and Hermes
calls back into JARVIS through the `jarvis` MCP server for anything on the Mac or
in the browser.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import AsyncIterator

import httpx

from shared.settings import DATA_DIR, HERMES_URL, ROOT, private_token

from .llm import LLMError

# Hermes's API-server surface for JARVIS: no terminal, no file writes, no code execution.
# Everything that touches the Mac or the browser goes through the `jarvis` MCP server,
# which enforces JARVIS's allowlists and approvals.
API_SERVER_TOOLSETS = ["web", "todo", "memory", "session_search", "skills", "jarvis"]


def hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def find_binary(override: str | None = None) -> str | None:
    for c in [override, os.getenv("JARVIS_HERMES_BIN"), shutil.which("hermes"),
              str(Path.home() / ".local/bin/hermes"), str(hermes_home() / "hermes-agent/venv/bin/hermes")]:
        if c and Path(c).exists() and os.access(c, os.X_OK):
            return c
    return None


def api_key(override: str | None = None) -> str:
    return (override or os.getenv("JARVIS_HERMES_API_KEY") or private_token("hermes_api_key")).strip()


def mcp_server_entry() -> dict:
    """How Hermes should launch the JARVIS MCP server."""
    py = ROOT / ".venv" / "bin" / "python"
    env = {"PYTHONPATH": str(ROOT), "JARVIS_ROOT": str(ROOT)}
    # Hermes gives MCP servers a minimal environment, and apps launched from Finder have a
    # short PATH — so pin node's absolute location for Playwright MCP.
    node = shutil.which("node") or next((p for p in ("/opt/homebrew/bin/node", "/usr/local/bin/node")
                                        if Path(p).exists()), None)
    if node:
        env["JARVIS_NODE"] = node
    return {
        "command": str(py if py.exists() else Path(sys.executable)),
        "args": ["-m", "jarvis_mcp.server"],
        "env": env,
        "timeout": 300,          # approvals can wait for you to click
        "connect_timeout": 60,
    }


def ensure_config(home: Path | None = None) -> dict:
    """Add the jarvis MCP server and the restricted api_server toolsets to Hermes's
    config.yaml. Keeps comments and every other setting; backs the file up once first."""
    from ruamel.yaml import YAML

    home = home or hermes_home()
    path = home / "config.yaml"
    yaml = YAML()
    yaml.preserve_quotes = True
    data = {}
    if path.exists():
        data = yaml.load(path.read_text()) or {}
    changed = []

    servers = data.get("mcp_servers") or {}
    want = mcp_server_entry()
    cur = servers.get("jarvis")
    def matches(c) -> bool:
        if not c:
            return False
        env = dict(c.get("env") or {})
        return (all(env.get(k) == v for k, v in want["env"].items()) and c.get("command") == want["command"]
                and list(c.get("args") or []) == want["args"]
                and all(c.get(k) == want[k] for k in ("timeout", "connect_timeout")))
    if not matches(cur):
        extra_env = {k: v for k, v in dict((cur or {}).get("env") or {}).items() if k not in want["env"]}
        want["env"].update(extra_env)   # keep env vars the user added
        servers["jarvis"] = want
        data["mcp_servers"] = servers
        changed.append("mcp_servers.jarvis")

    from . import router
    routes = router.configured_routes()
    gw = data.get("gateway") or {}
    plats = gw.get("platforms") or {}
    api = plats.get("api_server") or {}
    cur_routes = dict(api.get("model_routes") or {})
    if {k: dict(v) for k, v in cur_routes.items()} != routes:
        if routes:
            api["model_routes"] = routes
        else:
            api.pop("model_routes", None)
        if api:
            plats["api_server"] = api
        elif "api_server" in plats:
            plats.pop("api_server")
        if plats:
            gw["platforms"] = plats
        elif "platforms" in gw:
            gw.pop("platforms")
        if gw:
            data["gateway"] = gw
        elif "gateway" in data:
            data.pop("gateway")
        changed.append("gateway.platforms.api_server.model_routes")

    # Send JARVIS's tools to the model directly instead of hiding them behind tool_search:
    # that bridge costs two extra model round trips every time a tool is used.
    tools_cfg = data.get("tools") or {}
    ts = tools_cfg.get("tool_search") or {}
    if ts.get("enabled") != "off":
        ts["enabled"] = "off"
        tools_cfg["tool_search"] = ts
        data["tools"] = tools_cfg
        changed.append("tools.tool_search.enabled")

    pts = data.get("platform_toolsets") or {}
    if list(pts.get("api_server") or []) != API_SERVER_TOOLSETS:
        pts["api_server"] = list(API_SERVER_TOOLSETS)
        data["platform_toolsets"] = pts
        changed.append("platform_toolsets.api_server")

    if changed:
        home.mkdir(parents=True, exist_ok=True)
        backup = home / "config.yaml.before-jarvis"
        if path.exists() and not backup.exists():
            shutil.copy2(path, backup)
        tmp = path.with_suffix(".yaml.tmp")
        with tmp.open("w") as f:
            yaml.dump(data, f)
        tmp.replace(path)
    return {"path": str(path), "changed": changed}


PUBLIC_PROFILE = "jarvis-public"
# Keys copied from your main Hermes config so the receptionist uses the same model and provider.
_PUBLIC_COPY = ("model", "providers", "custom_providers", "fallback_model", "fallback_providers", "agent",
                "auxiliary", "compression", "timeouts")


def public_home() -> Path:
    return hermes_home() / "profiles" / PUBLIC_PROFILE


def ensure_public_config(home: Path | None = None) -> list[str]:
    """Write the receptionist profile's config: same model as your main Hermes, but no memory,
    no web/skills/session search, and only the `jarvis_public` MCP server (booking + messages)."""
    from ruamel.yaml import YAML
    home = home or public_home()
    main = hermes_home() / "config.yaml"
    y = YAML(typ="safe")
    src = (y.load(main.read_text()) or {}) if main.exists() else {}
    py = ROOT / ".venv" / "bin" / "python"
    want: dict = {k: src[k] for k in _PUBLIC_COPY if k in src}
    want["mcp_servers"] = {"jarvis_public": {
        "command": str(py if py.exists() else Path(sys.executable)), "args": ["-m", "jarvis_mcp.public_server"],
        "env": {"PYTHONPATH": str(ROOT), "JARVIS_ROOT": str(ROOT)}, "timeout": 120, "connect_timeout": 60}}
    want["platform_toolsets"] = {"api_server": ["jarvis_public"]}
    want["memory"] = {"memory_enabled": False, "user_profile_enabled": False}
    want["tools"] = {"tool_search": {"enabled": "off"}}
    # Its own small gateway (API server only), separate from your main one.
    want["gateway"] = {"standalone": True}
    path = home / "config.yaml"
    cur = (y.load(path.read_text()) or {}) if path.exists() else None
    if cur == want:
        return []
    home.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w") as f:
        YAML().dump(want, f)
    tmp.replace(path)
    # Env-based provider keys (if you put e.g. ANTHROPIC_API_KEY in ~/.hermes/.env) are shared too.
    main_env = hermes_home() / ".env"
    if main_env.exists():
        keep = [l for l in main_env.read_text().splitlines()
                if "=" in l and not l.lstrip().startswith("#") and not l.split("=", 1)[0].strip().startswith("API_SERVER")
                and any(t in l.split("=", 1)[0] for t in ("API_KEY", "BASE_URL", "WORKSPACE", "_ORG"))]
        env = home / ".env"
        existing = env.read_text().splitlines() if env.exists() else []
        names = {l.split("=", 1)[0] for l in existing if "=" in l}
        add = [l for l in keep if l.split("=", 1)[0] not in names]
        if add:
            env.write_text("\n".join(existing + add).strip() + "\n")
            os.chmod(env, 0o600)
    return ["config.yaml"]


def ensure_env(home: Path | None = None, key: str | None = None, port: int | None = None) -> list[str]:
    """Write the API-server settings into Hermes's own .env. Hermes treats API_SERVER_KEY
    as a profile secret and (on a normal install) only reads it from ~/.hermes/.env, not
    from the environment of the process that starts it. Other lines are kept untouched."""
    from shared.settings import HERMES_PORT
    home = home or hermes_home()
    path = home / ".env"
    want = {"API_SERVER_ENABLED": "true", "API_SERVER_KEY": key or api_key(),
            "API_SERVER_HOST": "127.0.0.1", "API_SERVER_PORT": str(port or HERMES_PORT)}
    lines = path.read_text().splitlines() if path.exists() else []
    seen, changed, out = set(), [], []
    for line in lines:
        name = line.split("=", 1)[0].strip().removeprefix("export ").strip() if "=" in line and not line.lstrip().startswith("#") else None
        if name in want:
            if name in seen:
                changed.append(name)
                continue                      # drop duplicates
            seen.add(name)
            new = f"{name}={want[name]}"
            if line.strip() != new:
                changed.append(name)
            out.append(new)
        else:
            out.append(line)
    for name, val in want.items():
        if name not in seen:
            out.append(f"{name}={val}")
            changed.append(name)
    if changed:
        home.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(out).rstrip("\n") + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    return sorted(set(changed))


def model_configured(home: Path | None = None) -> bool | None:
    """Best-effort: has the user picked a model/provider in Hermes? None = can't tell."""
    from ruamel.yaml import YAML
    path = (home or hermes_home()) / "config.yaml"
    if not path.exists():
        return False
    try:
        model = (YAML(typ="safe").load(path.read_text()) or {}).get("model")
    except Exception:
        return None
    if isinstance(model, str):
        return bool(model.strip())
    if isinstance(model, dict):
        return bool(model.get("default") or model.get("model"))
    return False


class HermesClient:
    def __init__(self, url: str = HERMES_URL, key: str | None = None):
        self.url = url.rstrip("/")
        self.key = key or api_key()
        self._model: str | None = None
        self._model_at = 0.0

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    async def health(self) -> dict:
        """{reachable, authorized, model, error}"""
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{self.url}/v1/models", headers=self._headers())
        except httpx.HTTPError:
            return {"reachable": False, "authorized": False, "model": None, "error": "Hermes isn't running"}
        if r.status_code in (401, 403):
            return {"reachable": True, "authorized": False, "model": None,
                    "error": "A Hermes gateway is running but rejected JARVIS's key (it was started outside JARVIS). "
                             "Stop it with `hermes gateway stop`, or paste its API_SERVER_KEY in Settings → Hermes."}
        if r.status_code != 200:
            return {"reachable": True, "authorized": False, "model": None, "error": f"Hermes returned {r.status_code}"}
        models = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        self._model, self._model_at = (models[0] if models else "hermes-agent"), time.time()
        return {"reachable": True, "authorized": True, "model": self._model, "error": None}

    async def model(self) -> str:
        if not self._model or time.time() - self._model_at > 300:
            await self.health()
        return self._model or "hermes-agent"

    async def stream(self, *, conversation: str, text: str, instructions: str, route: str | None = None,
                     effort: str | None = None) -> AsyncIterator[dict]:
        """Yield normalized events: text / tool_start / tool_result / done / error."""
        body = {"model": route or await self.model(), "input": text, "conversation": conversation,
                "instructions": instructions, "stream": True, "store": True}
        if effort:   # e.g. "low" for spoken turns: answer fast instead of thinking at length
            body["model_options"] = {"reasoning_effort": effort}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=None)) as c:
                async with c.stream("POST", f"{self.url}/v1/responses", json=body, headers=self._headers()) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode(errors="replace")[:400]
                        if r.status_code in (401, 403):
                            raise LLMError("Hermes rejected JARVIS's API key. Check Settings → Hermes.", "auth")
                        if r.status_code == 429:
                            raise LLMError("Hermes is busy (too many runs). Try again in a moment.", "rate_limit")
                        raise LLMError(f"Hermes error {r.status_code}: {detail}", "api")
                    names: dict[str, str] = {}
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            ev = json.loads(raw)
                        except ValueError:
                            continue
                        for out in _translate(ev, names):
                            yield out
        except httpx.ConnectError:
            raise LLMError("Hermes isn't running. JARVIS normally starts it — see Settings → Hermes.", "network") from None
        except httpx.HTTPError as e:
            raise LLMError(f"Lost connection to Hermes ({type(e).__name__}).", "network") from None


def display_tool_name(name: str) -> str:
    for p in ("mcp_jarvis_", "mcp__jarvis__", "jarvis__", "jarvis_"):
        if name.startswith(p):
            return name[len(p):]
    return name


def _output_text(item: dict) -> str:
    out = item.get("output")
    if isinstance(out, str):
        return out
    if isinstance(out, list):
        return "".join(p.get("text", "") for p in out if isinstance(p, dict))
    return json.dumps(out) if out is not None else ""


def _unwrap(text: str) -> str:
    """Hermes wraps tool output as {"result": "..."}; show the inner value."""
    try:
        v = json.loads(text)
    except ValueError:
        return text
    if isinstance(v, dict) and set(v) == {"result"}:
        inner = v["result"]
        return inner if isinstance(inner, str) else json.dumps(inner)
    return text


def _translate(ev: dict, names: dict[str, str]) -> list[dict]:
    t = ev.get("type", "")
    if t == "response.output_text.delta":
        return [{"type": "text", "delta": ev.get("delta", "")}]
    if t in ("response.output_item.added", "response.output_item.done"):
        item = ev.get("item") or {}
        it = item.get("type")
        if it == "function_call" and t == "response.output_item.added":
            names[item.get("call_id", "")] = item.get("name", "")
            try:
                args = json.loads(item.get("arguments") or "{}")
            except ValueError:
                args = {"raw": item.get("arguments")}
            return [{"type": "tool_start", "id": item.get("call_id"), "name": display_tool_name(item.get("name", "")),
                     "input": args}]
        if it == "function_call_output" and t == "response.output_item.done":
            text = _unwrap(_output_text(item))
            low = text[:300].lower()
            status = "error" if low.startswith("error") or "the user denied" in low or "did not run" in low else "ok"
            return [{"type": "tool_result", "id": item.get("call_id"),
                     "name": display_tool_name(names.get(item.get("call_id", ""), "")),
                     "status": status, "output": text[:20000]}]
        if it == "message" and item.get("phase") == "commentary" and t == "response.output_item.added":
            text = "".join(c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict))
            return [{"type": "text", "delta": text + "\n\n"}] if text else []
        return []
    if t == "response.completed":
        return [{"type": "done"}]
    if t in ("response.failed", "error"):
        resp = ev.get("response") or {}
        err = resp.get("error") or ev.get("error") or ev.get("message") or "Hermes failed"
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        return [{"type": "error", "message": str(err)}]
    return []
