"""Secret storage: env var first, then the macOS Keychain (via `keyring`), then a
0600 file in data/ as a last resort. Secrets never leave the backend."""
from __future__ import annotations

import os
import stat

from shared.settings import DATA_DIR

SERVICE = "jarvis-assistant"


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _file(name: str):
    return DATA_DIR / f".{name}"


def get_secret(name: str, env: str | None = None) -> tuple[str | None, str]:
    if env:
        v = os.getenv(env, "").strip()
        if v and "your" not in v and v != "change-me":
            return v, "env"
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, name)
            if v:
                return v, "keychain"
        except Exception:
            pass
    f = _file(name)
    if f.exists():
        return f.read_text().strip() or None, "file"
    return None, "none"


def set_secret(name: str, value: str) -> str:
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, name, value)
            return "keychain"
        except Exception:
            pass
    f = _file(name)
    f.write_text(value)
    os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)
    return "file"


def delete_secret(name: str) -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    _file(name).unlink(missing_ok=True)


def mask(key: str | None) -> str | None:
    return None if not key else f"…{key[-4:]}"
