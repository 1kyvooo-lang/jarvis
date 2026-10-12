"""Decides which Playwright MCP browser actions run freely and which need the user's OK.

Reading pages is free. Anything that could buy, send, submit, upload, run code or
leave the approved sites asks first. Rules live in permissions.json → "browser".
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

READ_ONLY = {
    "browser_snapshot", "browser_take_screenshot", "browser_find", "browser_console_messages",
    "browser_network_requests", "browser_network_request", "browser_wait_for",
    "browser_navigate_back", "browser_close", "browser_resize", "browser_hover", "browser_scroll",
}
BLOCKED_SCHEMES = {"file", "javascript", "data", "chrome", "about", "view-source"}
SENSITIVE_FIELD = re.compile(r"(?i)password|passcode|card number|credit card|cvv|cvc|security code|iban|ssn|social security|2fa|one-time code|otp")


def _domain_ok(url: str | None, perms: dict) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return bool(host) and any(host == d or host.endswith("." + d) for d in
                              (x.lower().strip().lstrip(".") for x in perms.get("approved_domains", [])))


def _risky(text: str, perms: dict) -> str | None:
    low = (text or "").lower()
    for w in perms.get("browser", {}).get("risky_words", []):
        if re.search(rf"(?<![a-z]){re.escape(w.lower())}(?![a-z])", low):
            return w
    return None


def assess(tool: str, args: dict, perms: dict, page_url: str | None) -> tuple[str, str]:
    """Return (decision, reason) where decision is 'allow', 'ask' or 'deny'."""
    policy = perms.get("browser", {})
    if tool in perms.get("disabled_tools", []):
        return "deny", f"{tool} is disabled in permissions"
    if tool in policy.get("always_ask", []):
        return "ask", f"{tool} always needs your approval"
    if tool in READ_ONLY:
        return "allow", "read-only"

    if tool in ("browser_navigate", "browser_tabs"):
        url = args.get("url")
        if tool == "browser_tabs" and not url:
            return "allow", "tab management"
        scheme = (urlparse(url or "").scheme or "").lower()
        if scheme in BLOCKED_SCHEMES:
            return "deny", f"{scheme}: URLs are blocked"
        if scheme not in ("http", "https"):
            return "deny", "only http(s) pages can be opened"
        if not _domain_ok(url, perms) and policy.get("ask_outside_approved_domains", True):
            return "ask", f"{urlparse(url).hostname} isn't on your approved sites"
        return "allow", "approved site"

    element = str(args.get("element", ""))
    on_approved = _domain_ok(page_url, perms)
    outside = "" if on_approved else f" on {urlparse(page_url or '').hostname or 'an unapproved site'}"

    if tool in ("browser_click", "browser_select_option", "browser_drag"):
        w = _risky(element + " " + " ".join(map(str, args.get("values", []) or [])), perms)
        if w:
            return "ask", f"clicking “{element[:60]}” looks consequential (“{w}”)"
        return "allow", "ordinary click"

    if tool == "browser_type":
        if SENSITIVE_FIELD.search(element):
            return "ask", f"typing into a sensitive field (“{element[:60]}”)"
        if args.get("submit"):
            w = _risky(element, perms)
            if w or not on_approved:
                return "ask", f"submitting{outside}" + (f" (“{w}”)" if w else "")
        return "allow", "typing"

    if tool == "browser_press_key":
        if str(args.get("key", "")).lower() in ("enter", "return") and not on_approved:
            return "ask", f"pressing Enter may submit a form{outside}"
        return "allow", "key press"

    return "ask", f"{tool} isn't in the known-safe list"
