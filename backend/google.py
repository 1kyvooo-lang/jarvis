"""Google: Gmail (read, sort, send) and Google Calendar (availability, booking).

You connect your own Google account once (Settings → Google). JARVIS uses your own
Google Cloud OAuth client, so your mail never passes through anyone else's servers. The
refresh token and client secret live in the macOS Keychain.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import re
import secrets
import time
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from shared.settings import BACKEND_PORT

from . import db, secrets_store

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"
SCOPES = ["openid", "email",
          "https://www.googleapis.com/auth/gmail.modify",       # read, label, archive (no permanent delete)
          "https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.readonly"]   # free/busy and your time zone
_transport: httpx.AsyncBaseTransport | None = None   # tests inject a mock Google
_token: dict[str, Any] = {"access": None, "exp": 0}
_states: dict[str, float] = {}
_cache: dict[str, Any] = {}


class GoogleError(RuntimeError):
    pass


# ---------------------------------------------------------------- config & OAuth

def cfg() -> dict:
    g = dict(db.get_settings().get("google") or {})
    g["client_secret"] = secrets_store.get_secret("google_client_secret")[0] or ""
    g["refresh_token"] = secrets_store.get_secret("google_refresh_token")[0] or ""
    return g


def connected() -> bool:
    g = cfg()
    return bool(g.get("client_id") and g["client_secret"] and g["refresh_token"])


def redirect_uri() -> str:
    return f"http://127.0.0.1:{BACKEND_PORT}/api/google/callback"


def status() -> dict:
    g = cfg()
    return {"client_configured": bool(g.get("client_id") and g["client_secret"]), "connected": connected(),
            "email": g.get("email") or None, "redirect_uri": redirect_uri()}


def auth_url() -> str:
    g = cfg()
    if not (g.get("client_id") and g["client_secret"]):
        raise GoogleError("Add your Google OAuth client ID and secret first.")
    state = secrets.token_urlsafe(24)
    _states[state] = time.time()
    return AUTH + "?" + urlencode({
        "client_id": g["client_id"], "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state,
        "include_granted_scopes": "true"})


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport, timeout=30)


async def finish_auth(code: str, state: str) -> str:
    if not state or _states.pop(state, 0) < time.time() - 900:
        raise GoogleError("This sign-in link expired. Click Connect Google again.")
    g = cfg()
    async with _client() as c:
        r = await c.post(TOKEN, data={"code": code, "client_id": g["client_id"], "client_secret": g["client_secret"],
                                      "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    j = r.json()
    if r.status_code >= 400 or "refresh_token" not in j:
        raise GoogleError(f"Google sign-in failed: {j.get('error_description') or j.get('error') or r.text[:200]}")
    secrets_store.set_secret("google_refresh_token", j["refresh_token"])
    _token.update(access=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    email = ""
    try:
        prof = await _req("GET", f"{GMAIL}/profile")
        email = prof.get("emailAddress", "")
    except GoogleError:
        pass
    s = db.get_settings()["google"]
    db.set_setting("google", {**s, "email": email})
    _cache.clear()
    db.log_activity(f"Google connected ({email or 'account'})", "info", tool="google", source="user")
    return email


def disconnect() -> None:
    secrets_store.delete_secret("google_refresh_token")
    _token.update(access=None, exp=0)
    _cache.clear()
    s = db.get_settings()["google"]
    db.set_setting("google", {**s, "email": ""})


async def _access() -> str:
    if _token["access"] and _token["exp"] > time.time():
        return _token["access"]
    g = cfg()
    if not g["refresh_token"]:
        raise GoogleError("Google isn't connected. Connect it in Settings → Google.")
    async with _client() as c:
        r = await c.post(TOKEN, data={"client_id": g.get("client_id"), "client_secret": g["client_secret"],
                                      "refresh_token": g["refresh_token"], "grant_type": "refresh_token"})
    j = r.json()
    if r.status_code >= 400:
        if j.get("error") == "invalid_grant":
            raise GoogleError("Google access was revoked or expired. Reconnect Google in Settings → Google.")
        raise GoogleError(f"Google token error: {j.get('error_description') or j.get('error')}")
    _token.update(access=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    return _token["access"]


async def _req(method: str, url: str, **kw) -> dict:
    for attempt in (0, 1):
        tok = await _access()
        async with _client() as c:
            r = await c.request(method, url, headers={"Authorization": f"Bearer {tok}"}, **kw)
        if r.status_code == 401 and attempt == 0:
            _token.update(access=None, exp=0)
            continue
        if r.status_code >= 400:
            try:
                msg = r.json().get("error", {}).get("message") or r.text
            except ValueError:
                msg = r.text
            raise GoogleError(f"Google error {r.status_code}: {msg}"[:300])
        return r.json() if r.content else {}
    raise GoogleError("Google authorization failed")


# ---------------------------------------------------------------- Gmail

def _headers(msg: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}


def _summary(msg: dict) -> dict:
    h = _headers(msg)
    return {"id": msg["id"], "thread_id": msg.get("threadId"), "from": h.get("from", ""), "to": h.get("to", ""),
            "subject": h.get("subject", "(no subject)"), "date": h.get("date", ""),
            "snippet": html.unescape(msg.get("snippet", "")), "unread": "UNREAD" in msg.get("labelIds", []),
            "labels": msg.get("labelIds", [])}


async def search(query: str = "in:inbox", max_results: int = 10) -> list[dict]:
    max_results = max(1, min(int(max_results or 10), 25))
    lst = await _req("GET", f"{GMAIL}/messages", params={"q": query, "maxResults": max_results})
    out = []
    for m in lst.get("messages", []):
        full = await _req("GET", f"{GMAIL}/messages/{m['id']}", params=[
            ("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "To"),
            ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")])
        out.append(_summary(full))
    return out


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _body(payload: dict) -> str:
    plain, rich = [], []
    def walk(p):
        mime = p.get("mimeType", "")
        data = p.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data).decode("utf-8", "replace"))
        elif data and mime == "text/html":
            rich.append(_b64(data).decode("utf-8", "replace"))
        for part in p.get("parts", []) or []:
            walk(part)
    walk(payload)
    if plain:
        return "\n".join(plain)
    if rich:
        t = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(rich))
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", t)
        return html.unescape(re.sub(r"<[^>]+>", " ", t))
    return ""


async def read(message_id: str) -> dict:
    msg = await _req("GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"})
    out = _summary(msg)
    body = re.sub(r"\n{3,}", "\n\n", _body(msg.get("payload", {}))).strip()
    out["body"] = body[:20000]
    out["truncated"] = len(body) > 20000
    h = _headers(msg)
    out["message_id_header"] = h.get("message-id", "")
    out["reply_to"] = h.get("reply-to", "")
    return out


async def _label_ids(names: list[str]) -> list[str]:
    system = {"inbox": "INBOX", "unread": "UNREAD", "starred": "STARRED", "important": "IMPORTANT",
              "spam": "SPAM", "trash": "TRASH"}
    labels = (await _req("GET", f"{GMAIL}/labels")).get("labels", [])
    by_name = {l["name"].lower(): l["id"] for l in labels}
    ids = []
    for n in names:
        n = n.strip()
        if not n:
            continue
        if n.lower() in system:
            ids.append(system[n.lower()])
        elif n.lower() in by_name:
            ids.append(by_name[n.lower()])
        else:
            new = await _req("POST", f"{GMAIL}/labels", json={"name": n, "labelListVisibility": "labelShow",
                                                               "messageListVisibility": "show"})
            by_name[n.lower()] = new["id"]
            ids.append(new["id"])
    return ids


async def organize(message_ids: list[str], add_labels: list[str] | None = None, remove_labels: list[str] | None = None,
                   archive: bool = False, mark_read: bool | None = None) -> dict:
    if not message_ids:
        raise GoogleError("No messages given")
    add = await _label_ids(add_labels or [])
    rem = await _label_ids(remove_labels or [])
    if "TRASH" in add or "SPAM" in add:
        raise GoogleError("Moving mail to trash or spam isn't allowed from JARVIS.")
    if archive:
        rem.append("INBOX")
    if mark_read is True:
        rem.append("UNREAD")
    elif mark_read is False:
        add.append("UNREAD")
    await _req("POST", f"{GMAIL}/messages/batchModify",
               json={"ids": message_ids[:100], "addLabelIds": add, "removeLabelIds": rem})
    return {"updated": len(message_ids[:100]), "added": add_labels or [], "removed": remove_labels or [],
            "archived": archive}


def _addresses(raw: str) -> list[str]:
    addrs = [a for _, a in getaddresses([raw]) if "@" in a]
    if not addrs:
        raise GoogleError(f"'{raw}' isn't a valid email address")
    return addrs


async def send(to: str, subject: str, body: str, reply_to_message_id: str | None = None, cc: str = "") -> dict:
    msg = EmailMessage()
    me = cfg().get("email") or ""
    if me:
        msg["From"] = me
    msg["To"] = ", ".join(_addresses(to))
    if cc:
        msg["Cc"] = ", ".join(_addresses(cc))
    payload: dict[str, Any] = {}
    if reply_to_message_id:
        orig = await read(reply_to_message_id)
        ref = orig.get("message_id_header")
        if ref:
            msg["In-Reply-To"] = ref
            msg["References"] = ref
        payload["threadId"] = orig.get("thread_id")
        if not subject:
            s = orig.get("subject", "")
            subject = s if s.lower().startswith("re:") else f"Re: {s}"
    msg["Subject"] = subject or "(no subject)"
    msg.set_content(body)
    payload["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = await _req("POST", f"{GMAIL}/messages/send", json=payload)
    return {"sent": True, "id": sent.get("id"), "to": msg["To"], "subject": msg["Subject"]}


def sender_email(raw_from: str) -> str:
    return parseaddr(raw_from)[1]


# ---------------------------------------------------------------- Calendar

async def timezone() -> str:
    if "tz" not in _cache:
        try:
            cal = await _req("GET", f"{CAL}/users/me/calendarList/primary")
            _cache["tz"] = cal.get("timeZone") or "UTC"
        except GoogleError:
            _cache["tz"] = local_tz()
    return _cache["tz"]


def local_tz() -> str:
    """This Mac's IANA time zone (e.g. Europe/Rome), falling back to UTC."""
    import os
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            ZoneInfo(name)
            return name
    except Exception:
        pass
    return "UTC"


def _parse(s: str, tz: ZoneInfo) -> dt.datetime:
    s = s.strip().replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


async def events(start: str | None = None, end: str | None = None, max_results: int = 25) -> dict:
    tz = ZoneInfo(await timezone())
    a = _parse(start, tz) if start else dt.datetime.now(tz)
    b = _parse(end, tz) if end else a + dt.timedelta(days=1)
    j = await _req("GET", f"{CAL}/calendars/primary/events", params={
        "timeMin": a.isoformat(), "timeMax": b.isoformat(), "singleEvents": "true", "orderBy": "startTime",
        "maxResults": max(1, min(int(max_results), 50))})
    out = []
    for e in j.get("items", []):
        out.append({"id": e.get("id"), "title": e.get("summary", "(busy)"), "start": e["start"].get("dateTime") or e["start"].get("date"),
                    "end": e["end"].get("dateTime") or e["end"].get("date"), "location": e.get("location", ""),
                    "attendees": [x.get("email") for x in e.get("attendees", [])][:10]})
    return {"timezone": str(tz), "events": out}


async def busy(a: dt.datetime, b: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    j = await _req("POST", f"{CAL}/freeBusy", json={"timeMin": a.isoformat(), "timeMax": b.isoformat(),
                                                     "items": [{"id": "primary"}]})
    tz = a.tzinfo
    return [(_parse(x["start"], tz), _parse(x["end"], tz))
            for x in j.get("calendars", {}).get("primary", {}).get("busy", [])]


def hours() -> dict:
    g = db.get_settings()["google"]
    h = g.get("business_hours") or {}
    return {"days": h.get("days") or [1, 2, 3, 4, 5], "start": h.get("start") or "09:00", "end": h.get("end") or "18:00",
            "slot_minutes": int(g.get("slot_minutes") or 30), "min_notice_hours": float(g.get("min_notice_hours") or 2)}


async def free_slots(from_date: str | None = None, days: int = 5, duration_minutes: int = 30, limit: int = 12) -> dict:
    """Free slots inside your working hours (Settings → Google), skipping anything already booked."""
    tz = ZoneInfo(await timezone())
    h = hours()
    now = dt.datetime.now(tz)
    earliest = now + dt.timedelta(hours=h["min_notice_hours"])
    day0 = _parse(from_date, tz).date() if from_date else now.date()
    days = max(1, min(int(days or 5), 21))
    dur = dt.timedelta(minutes=max(10, min(int(duration_minutes or 30), 240)))
    step = dt.timedelta(minutes=h["slot_minutes"])
    a = dt.datetime.combine(day0, dt.time(0), tz)
    b = a + dt.timedelta(days=days)
    taken = await busy(a, b)
    sh, sm = map(int, h["start"].split(":"))
    eh, em = map(int, h["end"].split(":"))
    slots = []
    for i in range(days):
        d = day0 + dt.timedelta(days=i)
        if d.isoweekday() not in h["days"]:
            continue
        t = dt.datetime.combine(d, dt.time(sh, sm), tz)
        close = dt.datetime.combine(d, dt.time(eh, em), tz)
        while t + dur <= close and len(slots) < limit:
            if t >= earliest and not any(s < t + dur and t < e for s, e in taken):
                slots.append({"start": t.isoformat(), "end": (t + dur).isoformat(),
                              "label": t.strftime("%a %d %b, %H:%M")})
            t += step
    return {"timezone": str(tz), "duration_minutes": int(dur.total_seconds() // 60), "slots": slots}


async def is_free(start: dt.datetime, end: dt.datetime) -> bool:
    return not any(s < end and start < e for s, e in await busy(start - dt.timedelta(minutes=1), end + dt.timedelta(minutes=1)))


def within_hours(start: dt.datetime, end: dt.datetime) -> bool:
    h = hours()
    sh, sm = map(int, h["start"].split(":"))
    eh, em = map(int, h["end"].split(":"))
    return (start.isoweekday() in h["days"] and start.date() == end.date()
            and start.time() >= dt.time(sh, sm) and end.time() <= dt.time(eh, em))


async def create_event(title: str, start: str, end: str | None = None, description: str = "",
                       attendee_email: str | None = None, duration_minutes: int = 30, location: str = "") -> dict:
    tz = ZoneInfo(await timezone())
    a = _parse(start, tz)
    b = _parse(end, tz) if end else a + dt.timedelta(minutes=int(duration_minutes or 30))
    if b <= a:
        raise GoogleError("The end time must be after the start time")
    body: dict[str, Any] = {"summary": title[:200], "description": description[:4000], "location": location[:300],
                            "start": {"dateTime": a.isoformat(), "timeZone": str(tz)},
                            "end": {"dateTime": b.isoformat(), "timeZone": str(tz)}}
    params = {}
    if attendee_email:
        body["attendees"] = [{"email": x} for x in _addresses(attendee_email)]
        params["sendUpdates"] = "all"
    ev = await _req("POST", f"{CAL}/calendars/primary/events", json=body, params=params)
    return {"created": True, "id": ev.get("id"), "title": ev.get("summary"), "start": a.isoformat(), "end": b.isoformat(),
            "link": ev.get("htmlLink")}
