"""Built-in agent tools. Each handler gets (args, permissions) and returns JSON-able data.

No tool runs a shell. Subprocesses use fixed argv lists; user input is never
interpolated into a command string.
"""
from __future__ import annotations

import datetime as dt
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import psutil

from .registry import ToolError, tool
from .safety import TEXT_EXTENSIONS, approved_roots, check_app, check_url, is_denied, resolve_inside_roots

IS_MAC = sys.platform == "darwin"


def _run(argv: list[str], timeout: float = 10) -> str:
    out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if out.returncode != 0:
        raise ToolError((out.stderr or out.stdout or "command failed").strip()[:300])
    return out.stdout.strip()


def _require_mac():
    if not IS_MAC:
        raise ToolError(f"This tool only works on macOS (agent is running on {sys.platform})")


# ---------------------------------------------------------------- read-only

@tool(name="get_datetime", category="system",
      description="Get the current local date, time, weekday and timezone on the user's Mac.",
      input_schema={"properties": {}})
def get_datetime(args, perms):
    now = dt.datetime.now().astimezone()
    return {"iso": now.isoformat(timespec="seconds"), "date": now.strftime("%A %d %B %Y"),
            "time": now.strftime("%H:%M:%S"), "timezone": str(now.tzinfo)}


@tool(name="system_status", category="system",
      description="Report live system status: CPU load, memory, disk usage, battery and uptime.",
      input_schema={"properties": {}})
def system_status(args, perms):
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(str(Path.home()))
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_count": psutil.cpu_count(),
        "load_avg": [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else None,
        "memory": {"total_gb": round(vm.total / 1e9, 1), "used_percent": vm.percent},
        "disk_home": {"total_gb": round(du.total / 1e9, 1), "free_gb": round(du.free / 1e9, 1), "used_percent": du.percent},
        "battery": None if not bat else {"percent": bat.percent, "plugged_in": bat.power_plugged},
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


@tool(name="system_info", category="system",
      description="Read-only system information. topic: 'os' (version/hostname), 'hardware' (CPU/RAM), 'network' (interfaces, no secrets), 'disks'.",
      input_schema={"properties": {"topic": {"type": "string", "enum": ["os", "hardware", "network", "disks"]}},
                    "required": ["topic"]})
def system_info(args, perms):
    topic = args["topic"]
    if topic == "os":
        info = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                "hostname": platform.node(), "python": platform.python_version()}
        if IS_MAC:
            info["macos"] = _run(["sw_vers", "-productVersion"])
        return info
    if topic == "hardware":
        info = {"cpu_count_logical": psutil.cpu_count(), "cpu_count_physical": psutil.cpu_count(logical=False),
                "memory_gb": round(psutil.virtual_memory().total / 1e9, 1), "processor": platform.processor()}
        if IS_MAC:
            try:
                info["cpu_brand"] = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
            except ToolError:
                pass
        return info
    if topic == "network":
        out = {}
        for name, addrs in psutil.net_if_addrs().items():
            ips = [a.address for a in addrs if a.family.name in ("AF_INET", "AF_INET6")]
            if ips:
                out[name] = ips
        return {"interfaces": out}
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({"mount": p.mountpoint, "total_gb": round(u.total / 1e9, 1), "used_percent": u.percent})
        except (PermissionError, OSError):
            continue
    return {"disks": disks}


@tool(name="search_files", category="files", timeout=25,
      description="Search file and folder names inside the user's approved directories. Case-insensitive substring match.",
      input_schema={"properties": {
          "query": {"type": "string", "minLength": 1, "maxLength": 200},
          "directory": {"type": "string", "maxLength": 500, "description": "Optional: an approved directory or subfolder of one."},
          "max_results": {"type": "integer", "minimum": 1, "maximum": 100}},
          "required": ["query"]})
def search_files(args, perms):
    q = args["query"].lower()
    limit = args.get("max_results", 25)
    roots = [resolve_inside_roots(args["directory"], perms)] if args.get("directory") else approved_roots(perms)
    if not roots:
        raise ToolError("No approved directories are configured")
    results, scanned, deadline = [], 0, time.time() + 15
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "Library")]
            for name in dirnames + filenames:
                scanned += 1
                if q in name.lower():
                    p = Path(dirpath) / name
                    if is_denied(p):
                        continue
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    results.append({"path": str(p), "is_dir": p.is_dir(), "size": st.st_size,
                                    "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
                    if len(results) >= limit:
                        return {"results": results, "truncated": True, "scanned": scanned}
            if time.time() > deadline:
                return {"results": results, "truncated": True, "scanned": scanned, "note": "time limit reached"}
    return {"results": results, "truncated": False, "scanned": scanned}


@tool(name="read_text_file", category="files", sensitive=False,
      description="Read a text file (txt, md, csv, json, code...) inside the approved directories so it can be summarized. Max 200 KB.",
      input_schema={"properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}}, "required": ["path"]})
def read_text_file(args, perms):
    path = resolve_inside_roots(args["path"], perms)
    if not path.is_file():
        raise ToolError("File not found")
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        raise ToolError(f"File type '{path.suffix}' is not an allowed text type")
    size = path.stat().st_size
    if size > 200_000:
        raise ToolError(f"File is too large ({size} bytes, max 200000)")
    text = path.read_text(errors="replace")
    return {"path": str(path), "size": size, "content": text[:60_000], "truncated": len(text) > 60_000}


# ---------------------------------------------------------------- actions

@tool(name="open_app", category="apps", mac_only=True,
      description="Open an application on the Mac. Only apps on the user's approved list can be opened.",
      input_schema={"properties": {"name": {"type": "string", "minLength": 1, "maxLength": 100}}, "required": ["name"]})
def open_app(args, perms):
    app = check_app(args["name"], perms)
    _require_mac()
    _run(["open", "-a", app])
    return {"opened": app}


@tool(name="open_url", category="browser", mac_only=True,
      description="Open a website in the user's default browser. Only approved domains are allowed.",
      input_schema={"properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}}, "required": ["url"]})
def open_url(args, perms):
    url = check_url(args["url"], perms)
    _require_mac()
    _run(["open", url])
    return {"opened": url}


@tool(name="notify", category="system", mac_only=True,
      description="Show a macOS notification banner with a title and message.",
      input_schema={"properties": {"title": {"type": "string", "maxLength": 80},
                                   "message": {"type": "string", "minLength": 1, "maxLength": 300}},
                    "required": ["message"]})
def notify(args, perms):
    _require_mac()
    # Text is passed as argv to the script, never spliced into AppleScript source.
    script = 'on run argv\n display notification (item 2 of argv) with title (item 1 of argv)\nend run'
    _run(["osascript", "-e", script, args.get("title") or "JARVIS", args["message"]])
    return {"notified": True}

