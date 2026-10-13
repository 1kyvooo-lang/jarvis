"""Email & calendar, whichever way you connected Google.

  • "mac"    — your Google account added on the Mac (System Settings → Internet Accounts). JARVIS works
               through the Mail and Calendar apps. No developer keys, just the normal Google sign-in.
  • "google" — direct Google API with your own OAuth client (Settings → Google → Advanced).

Every email/calendar feature (the email_* and calendar_* tools, the receptionist, the inbox assistant and
the morning briefing) goes through this module, so they work the same either way.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from zoneinfo import ZoneInfo

from . import agent_client, db, google

GoogleError = google.GoogleError
hours = google.hours
within_hours = google.within_hours
sender_email = google.sender_email


def mac_enabled() -> bool:
    return bool((db.get_settings().get("mailcal") or {}).get("mac"))


def provider() -> str | None:
    if google.connected():
        return "google"
    if mac_enabled():
        return "mac"
    return None


def connected() -> bool:
    return provider() is not None


async def _mac(tool: str, args: dict, timeout_note: str = "") -> dict:
    res = await agent_client.execute(f"mailcal-{uuid.uuid4().hex[:10]}", tool, args, approved=True)
    if not res.get("ok"):
        raise GoogleError(res.get("error") or f"The Mac's {timeout_note or 'Mail/Calendar app'} didn't answer.")
    return res.get("output") or {}


# ---------------------------------------------------------------- email

def _parse_query(q: str) -> dict:
    """Understand the common Gmail-style bits of a query for the Mail app."""
    q = q or ""
    out = {"unread_only": "is:unread" in q, "days": 0, "query": ""}
    m = re.search(r"newer_than:(\d+)([dhm])", q)
    if m:
        n = int(m.group(1))
        out["days"] = n if m.group(2) == "d" else n / 24 if m.group(2) == "h" else n * 30
    words = []
    for tok in q.split():
        if tok.startswith(("from:", "subject:")):
            words.append(tok.split(":", 1)[1].strip('"'))
        elif ":" in tok or tok.startswith("-"):
            continue                       # in:inbox, label:, category: … aren't available in Mail
        else:
            words.append(tok.strip('"'))
    out["query"] = " ".join(w for w in words if w)
    return out


async def search(query: str = "in:inbox", max_results: int = 10) -> list[dict]:
    p = provider()
    if p == "google":
        return await google.search(query, max_results)
    if p != "mac":
        raise GoogleError("Email isn't connected. Settings → Google.")
    q = _parse_query(query)
    rows = (await _mac("mac_mail_list", {**q, "max_results": max(1, min(int(max_results or 10), 25))}, "Mail app"))["messages"]
    return [{"id": r["id"], "thread_id": None, "from": r["from"], "to": "", "subject": r["subject"], "date": r["date"],
             "snippet": "", "unread": r["unread"], "labels": []} for r in rows]


async def read(message_id: str) -> dict:
    p = provider()
    if p == "google":
        return await google.read(message_id)
    r = await _mac("mac_mail_read", {"id": str(message_id)}, "Mail app")
    body = re.sub(r"\n{3,}", "\n\n", r.get("body") or "").strip()
    return {"id": r["id"], "thread_id": None, "from": r["from"], "to": r.get("to", ""), "subject": r["subject"],
            "date": r["date"], "snippet": body[:160], "unread": r.get("unread"), "labels": [], "body": body[:20000],
            "truncated": len(body) > 20000, "message_id_header": "", "reply_to": r.get("reply_to", "")}


async def organize(message_ids: list[str], add_labels: list[str] | None = None, remove_labels: list[str] | None = None,
                   archive: bool = False, mark_read: bool | None = None) -> dict:
    p = provider()
    if p == "google":
        return await google.organize(message_ids, add_labels, remove_labels, archive, mark_read)
    if any(str(l).upper() in ("TRASH", "SPAM") for l in (add_labels or [])):
        raise GoogleError("Moving mail to trash or spam isn't allowed from JARVIS.")
    args: dict = {"ids": [str(i) for i in message_ids][:100]}
    if mark_read is not None:
        args["mark_read"] = bool(mark_read)
    labels = [l for l in (add_labels or []) if l.upper() not in ("INBOX", "UNREAD", "STARRED", "IMPORTANT")]
    if archive and labels:
        args["move_to"] = labels[0].replace("/", " ")       # a mailbox (= a Gmail label) next to the inbox
    elif archive:
        args["archive"] = True
    elif labels or "STARRED" in [l.upper() for l in (add_labels or [])]:
        args["flag"] = 1                                      # orange flag: “sorted, look at this”
    r = await _mac("mac_mail_organize", args, "Mail app")
    return {"updated": r.get("updated", 0), "added": add_labels or [], "removed": remove_labels or [], "archived": archive}


async def send(to: str, subject: str, body: str, reply_to_message_id: str | None = None, cc: str = "") -> dict:
    p = provider()
    if p == "google":
        return await google.send(to, subject, body, reply_to_message_id, cc)
    google._addresses(to)               # validate
    r = await _mac("mac_mail_send", {"to": to, "subject": subject or "", "body": body, "cc": cc or "",
                                     "reply_to_id": str(reply_to_message_id or "")}, "Mail app")
    return {"sent": True, "id": None, "to": to, "subject": r.get("subject") or subject}


# ---------------------------------------------------------------- calendar

async def timezone() -> str:
    return await google.timezone() if provider() == "google" else google.local_tz()


def _parse(s: str, tz: ZoneInfo) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=tz)


async def _mac_events(a: dt.datetime, b: dt.datetime) -> list[dict]:
    return (await _mac("mac_calendar_events", {"start": a.isoformat(), "end": b.isoformat()}, "Calendar app"))["events"]


async def events(start: str | None = None, end: str | None = None, max_results: int = 25) -> dict:
    p = provider()
    if p == "google":
        return await google.events(start, end, max_results)
    tz = ZoneInfo(await timezone())
    a = _parse(start, tz) if start else dt.datetime.now(tz)
    b = _parse(end, tz) if end else a + dt.timedelta(days=1)
    evs = await _mac_events(a, b)
    return {"timezone": str(tz), "events": [
        {"id": None, "title": e["title"], "start": _parse(e["start"], tz).astimezone(tz).isoformat(),
         "end": _parse(e["end"], tz).astimezone(tz).isoformat(), "location": e.get("location", ""), "attendees": [],
         "calendar": e.get("calendar")} for e in evs][:max_results]}


async def busy(a: dt.datetime, b: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    if provider() == "google":
        return await google.busy(a, b)
    tz = a.tzinfo
    return [(_parse(e["start"], tz), _parse(e["end"], tz)) for e in await _mac_events(a, b) if not e.get("allday")]


async def free_slots(from_date: str | None = None, days: int = 5, duration_minutes: int = 30, limit: int = 12) -> dict:
    """Free slots inside your working hours, skipping anything already booked."""
    tz = ZoneInfo(await timezone())
    h = hours()
    now = dt.datetime.now(tz)
    earliest = now + dt.timedelta(hours=h["min_notice_hours"])
    day0 = _parse(from_date, tz).date() if from_date else now.date()
    days = max(1, min(int(days or 5), 21))
    dur = dt.timedelta(minutes=max(10, min(int(duration_minutes or 30), 240)))
    step = dt.timedelta(minutes=h["slot_minutes"])
    a = dt.datetime.combine(day0, dt.time(0), tz)
    taken = await busy(a, a + dt.timedelta(days=days))
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
                slots.append({"start": t.isoformat(), "end": (t + dur).isoformat(), "label": t.strftime("%a %d %b, %H:%M")})
            t += step
    return {"timezone": str(tz), "duration_minutes": int(dur.total_seconds() // 60), "slots": slots}


async def is_free(start: dt.datetime, end: dt.datetime) -> bool:
    return not any(s < end and start < e for s, e in await busy(start - dt.timedelta(minutes=1), end + dt.timedelta(minutes=1)))


async def create_event(title: str, start: str, end: str | None = None, description: str = "",
                       attendee_email: str | None = None, duration_minutes: int = 30, location: str = "") -> dict:
    p = provider()
    if p == "google":
        return await google.create_event(title, start, end, description, attendee_email, duration_minutes, location)
    tz = ZoneInfo(await timezone())
    a = _parse(start, tz)
    b = _parse(end, tz) if end else a + dt.timedelta(minutes=int(duration_minutes or 30))
    if b <= a:
        raise GoogleError("The end time must be after the start time")
    note = description + (f"\nInvitee: {attendee_email}" if attendee_email else "")
    r = await _mac("mac_calendar_create", {"title": title[:200], "start": a.isoformat(), "end": b.isoformat(),
                                           "notes": note[:4000], "location": location[:300],
                                           "calendar": (db.get_settings().get("mailcal") or {}).get("calendar", "")},
                   "Calendar app")
    out = {"created": True, "id": None, "title": title, "start": a.isoformat(), "end": b.isoformat(), "calendar": r.get("calendar")}
    if attendee_email:
        out["note"] = "Added to your calendar. (Invites to other people need the Google connection; send them an email instead.)"
    return out


async def test() -> dict:
    """Quick check that email and calendar both answer."""
    out: dict = {"provider": provider()}
    try:
        out["recent_emails"] = [m["subject"] for m in await search("in:inbox", 3)]
    except Exception as e:
        out["email_error"] = str(e)[:300]
    try:
        now = dt.datetime.now().astimezone()
        out["events_today"] = len((await events(now.isoformat(), now.replace(hour=23, minute=59).isoformat()))["events"])
    except Exception as e:
        out["calendar_error"] = str(e)[:300]
    return out
