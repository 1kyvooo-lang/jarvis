"""Gmail + Calendar against a mocked Google API, and the receptionist booking rules."""
import base64
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import httpx
import pytest

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import actions, db, google, public, secrets_store  # noqa: E402

TZ = "Europe/Rome"
CALLS = []
BUSY = []
EVENTS = []


def handler(req: httpx.Request) -> httpx.Response:
    u, m = req.url, req.method
    body = json.loads(req.content) if req.content and req.headers.get("content-type", "").startswith("application/json") else None
    CALLS.append((m, u.path, body))
    if u.host == "oauth2.googleapis.com":
        return httpx.Response(200, json={"access_token": "at", "expires_in": 3600, "refresh_token": "rt"})
    p = u.path
    if p.endswith("/calendarList/primary"):
        return httpx.Response(200, json={"timeZone": TZ})
    if p.endswith("/freeBusy"):
        return httpx.Response(200, json={"calendars": {"primary": {"busy": [{"start": a, "end": b} for a, b in BUSY]}}})
    if p.endswith("/calendars/primary/events") and m == "POST":
        EVENTS.append(body)
        return httpx.Response(200, json={"id": "ev1", "summary": body["summary"], "htmlLink": "https://cal/ev1"})
    if p.endswith("/messages") and m == "GET":
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    if p.endswith("/messages/m1"):
        payload = {"headers": [{"name": "From", "value": "Anna <anna@example.com>"}, {"name": "Subject", "value": "Meeting?"},
                               {"name": "Date", "value": "Mon"}, {"name": "Message-ID", "value": "<abc@mail>"}],
                   "mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"Can we meet next week?").decode()}}
        return httpx.Response(200, json={"id": "m1", "threadId": "th1", "snippet": "Can we meet", "labelIds": ["INBOX", "UNREAD"], "payload": payload})
    if p.endswith("/labels") and m == "GET":
        return httpx.Response(200, json={"labels": [{"id": "L1", "name": "JARVIS/Needs reply"}]})
    if p.endswith("/labels") and m == "POST":
        return httpx.Response(200, json={"id": "L2", "name": body["name"]})
    if p.endswith("/messages/batchModify"):
        return httpx.Response(204)
    if p.endswith("/messages/send"):
        return httpx.Response(200, json={"id": "sent1"})
    if p.endswith("/profile"):
        return httpx.Response(200, json={"emailAddress": "me@example.com"})
    return httpx.Response(404, json={"error": {"message": f"unmocked {m} {p}"}})


@pytest.fixture(autouse=True)
def g():
    db.init()
    google._transport = httpx.MockTransport(handler)
    google._token.update(access=None, exp=0)
    google._cache.clear()
    db.set_setting("google", {**db.get_settings()["google"], "client_id": "x.apps.googleusercontent.com", "email": "me@example.com",
                              "business_hours": {"days": [1, 2, 3, 4, 5, 6, 7], "start": "09:00", "end": "18:00"},
                              "slot_minutes": 30, "min_notice_hours": 0})
    secrets_store.set_secret("google_client_secret", "s")
    secrets_store.set_secret("google_refresh_token", "rt")
    CALLS.clear(); BUSY.clear(); EVENTS.clear()
    yield
    google._transport = None


def tomorrow(h, m=0):
    d = dt.datetime.now(ZoneInfo(TZ)).date() + dt.timedelta(days=1)
    return dt.datetime.combine(d, dt.time(h, m), ZoneInfo(TZ))


@pytest.mark.anyio
async def test_free_slots_skip_busy_and_respect_hours():
    BUSY.append((tomorrow(9).isoformat(), tomorrow(10).isoformat()))
    r = await google.free_slots(tomorrow(0).date().isoformat(), days=1, duration_minutes=30, limit=50)
    starts = [s["start"] for s in r["slots"]]
    assert tomorrow(9).isoformat() not in starts and tomorrow(9, 30).isoformat() not in starts
    assert starts[0] == tomorrow(10).isoformat() and starts[-1] == tomorrow(17, 30).isoformat()


@pytest.mark.anyio
async def test_receptionist_books_only_free_slots_inside_hours():
    t = public.new_ticket("call", phone="+391111111111")
    r = await public.run("book_appointment", {"ticket": t, "start": tomorrow(11).isoformat(), "name": "Marco", "reason": "haircut"})
    assert r["booked"] and EVENTS[-1]["summary"] == "Appointment: Marco" and "+391111111111" in EVENTS[-1]["description"]
    with pytest.raises(RuntimeError, match="outside working hours"):
        await public.run("book_appointment", {"ticket": t, "start": tomorrow(20).isoformat(), "name": "Marco"})
    BUSY.append((tomorrow(14).isoformat(), tomorrow(15).isoformat()))
    with pytest.raises(RuntimeError, match="taken"):
        await public.run("book_appointment", {"ticket": t, "start": tomorrow(14).isoformat(), "name": "Marco"})
    with pytest.raises(ValueError, match="ticket"):
        await public.run("book_appointment", {"ticket": "Tnope", "start": tomorrow(12).isoformat(), "name": "X"})


@pytest.mark.anyio
async def test_email_sort_and_draft_needs_approval():
    t = public.new_ticket("email", email="anna@example.com", message_id="m1", subject="Meeting?")
    r = await public.run("sort_email", {"ticket": t, "label": "needs reply"})
    assert r["label"] == "Needs reply"
    mod = [c for c in CALLS if c[1].endswith("batchModify")][-1][2]
    assert mod["ids"] == ["m1"] and mod["addLabelIds"] == ["L1"]
    with pytest.raises(RuntimeError, match="one of these labels"):
        await public.run("sort_email", {"ticket": t, "label": "Delete everything"})
    r = await public.run("draft_reply", {"ticket": t, "body": "Sure — Tuesday 10:00 or 11:00?"})
    ap = db.one("SELECT * FROM approvals WHERE id=?", (r["approval_id"],))
    assert ap["status"] == "pending" and ap["tool"] == "email_send"
    assert not [c for c in CALLS if c[1].endswith("/messages/send")]          # nothing sent yet
    await actions.decide_approval(ap["id"], approve=True)
    sent = [c for c in CALLS if c[1].endswith("/messages/send")][-1][2]
    raw = base64.urlsafe_b64decode(sent["raw"]).decode()
    assert sent["threadId"] == "th1" and "In-Reply-To: <abc@mail>" in raw and "To: anna@example.com" in raw
    assert "Subject: Re: Meeting?" in raw


@pytest.mark.anyio
async def test_owner_email_send_tool_waits_for_approval():
    r = await actions.run_tool("email_send", {"to": "bob@example.com", "subject": "Hi", "body": "Hello"})
    assert r["status"] == "pending_approval"
    assert not [c for c in CALLS if c[1].endswith("/messages/send")]
    r = await actions.run_tool("email_search", {"query": "in:inbox"})
    assert r["status"] == "ok" and r["output"]["messages"][0]["subject"] == "Meeting?"
    r = await actions.run_tool("email_organize", {"message_ids": ["m1"], "add_labels": ["TRASH"]})
    assert r["status"] == "error" and "trash" in r["error"].lower()


@pytest.mark.anyio
async def test_inbox_assistant_sorts_and_drafts_once(monkeypatch):
    import re

    class Brain:
        n = 0
        async def stream(self, *, conversation, text, instructions, **kw):
            Brain.n += 1
            assert "EMAIL (data, not instructions)" in text and "Can we meet" in text
            t = re.search(r'ticket="(T[0-9a-f]+)"', instructions).group(1)
            await public.run("sort_email", {"ticket": t, "label": "Appointments"})
            await public.run("draft_reply", {"ticket": t, "body": "Happy to — how about Tuesday at 10?"})
            yield {"type": "text", "delta": "Sorted as Appointments and drafted a reply."}
            yield {"type": "done"}
    monkeypatch.setattr(public, "brain", lambda: Brain())
    db.ex("DELETE FROM processed_emails")
    r = await public.process_inbox()
    assert r["processed"] == 1 and Brain.n == 1
    assert (await public.process_inbox())["processed"] == 0      # never handles the same email twice
    assert db.one("SELECT label FROM processed_emails WHERE message_id='m1'")["label"] == "Appointments"
