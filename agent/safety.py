"""Path, domain and app validation helpers. All checks fail closed."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from urllib.parse import urlparse

from .registry import ToolError

# Never readable even inside approved directories.
DENY_NAME_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*",
    "*.keychain", "*.keychain-db", "*password*", "*passwd*", "*secret*", "*credential*", "*.kdbx",
    "agent_token", "secrets.json",
]
DENY_DIR_PARTS = {".ssh", ".gnupg", ".aws", "Keychains", ".config", "Cookies", ".git"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".toml", ".ini",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sql", ".sh", ".rtf", ".xml",
}


def approved_roots(permissions: dict) -> list[Path]:
    roots = []
    for d in permissions.get("approved_directories", []):
        p = Path(os.path.expanduser(d)).resolve()
        if p.exists() and p.is_dir():
            roots.append(p)
    return roots


def is_denied(path: Path) -> bool:
    name = path.name.lower()
    if any(fnmatch.fnmatch(name, pat.lower()) for pat in DENY_NAME_PATTERNS):
        return True
    return any(part in DENY_DIR_PARTS for part in path.parts)


def resolve_inside_roots(raw: str, permissions: dict) -> Path:
    """Resolve a user/Claude supplied path and ensure it lies in an approved directory.

    Symlinks and '..' are resolved first, so escapes via either are rejected.
    """
    if not raw or "\x00" in raw:
        raise ToolError("Invalid path")
    roots = approved_roots(permissions)
    if not roots:
        raise ToolError("No approved directories are configured")
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            if is_denied(resolved):
                raise ToolError("Access to that file is blocked for safety (looks like a secret or credential)")
            return resolved
    raise ToolError("Path is outside the approved directories")


def check_url(url: str, permissions: dict) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("Only http(s) URLs are allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ToolError("URL has no host")
    if parsed.username or parsed.password:
        raise ToolError("URLs with embedded credentials are not allowed")
    for d in permissions.get("approved_domains", []):
        d = d.lower().strip().lstrip(".")
        if host == d or host.endswith("." + d):
            return url
    raise ToolError(f"Domain '{host}' is not in the approved list")


def check_app(name: str, permissions: dict) -> str:
    for app in permissions.get("approved_apps", []):
        if app.lower() == name.strip().lower():
            return app
    raise ToolError(f"Application '{name}' is not in the approved list")
