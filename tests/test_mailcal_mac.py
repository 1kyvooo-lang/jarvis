"""Email & calendar through the Mac's Mail and Calendar apps (agent simulated)."""
import datetime as dt
import os
from zoneinfo import ZoneInfo

import pytest

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import actions, agent_client, db, google, mailcal, public, secrets_store  # noqa: E402

CALLS = []
EVENTS = []


async def fake_execute(rid, tool, args, approved=False):
    CALLS.append((tool, args, approved))
    if tool == "mac_mail_list":
        return {"ok": True, "output": {"messages": [{"id": "101", "subject": "Lunch Friday?", "from": "Anna <anna@x.com>",
                                                     "date": "2026-10-13T09:00:00Z", "unread": True}]}}
    if tool == "mac_mail_read":
        return {"ok": True, "output": {"id": "101", "subject": "Lunch Friday?", "from": "Anna <anna@x.com>", "to": "me@x.com",
                                       "date": "2026-10-13T09:00:00Z", "reply_to": "", "body": "Can we meet?", "unread": True}}
    if tool == "mac_calendar_events":
        return {"ok": True, "output": {"events": EVENTS}}
    if tool in ("mac_calendar_create", "mac_mail_send", "mac_mail_organize"):
        return {"ok": True, "output": {"created": True, "calendar": "me@gmail.com", "sent": True, "updated": len(args.get("ids", [1]))}}
    return {"ok": False, "error": "unknown"}


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    db.init()
    secrets_store.delete_secret("google_refresh_token")        # no Google API → Mac accounts
    db.set_setting("mailcal", {"mac": True, "calendar": ""})
    db.set_setting("google", {**db.get_settings()["google"], "business_hours": {"days": [1, 2, 3, 4, 5, 6, 7], "start": "09:00", "end": "18:00"},
                              "slot_minutes": 30, "min_notice_hours": 0})
    monkeypatch.setattr(agent_client, "execute", fake_execute)
    monkeypatch.setattr(google, "local_tz", lambda: "Europe/Rome")
    CALLS.clear(); EVENTS.clear()
    yield
    db.set_setting("mailcal", {"mac": False, "calendar": ""})


def test_provider_is_mac():
    assert mailcal.provider() == "mac" and mailcal.connected()


@pytest.mark.anyio
async def test_gmail_style_query_is_understood():
    r = await actions.run_tool("email_search", {"query": "in:inbox is:unread newer_than:2d from:anna", "max_results": 5})
    assert r["status"] == "ok" and r["output"]["messages"][0]["subject"] == "Lunch Friday?"
    tool, args, approved = CALLS[-1]
    assert tool == "mac_mail_list" and args["unread_only"] and args["days"] == 2 and args["query"] == "anna" and approved


@pytest.mark.anyio
async def test_send_waits_for_approval_then_uses_mail_app():
    r = await actions.run_tool("email_send", {"to": "anna@x.com", "subject": "Re", "body": "Friday works", "reply_to_message_id": "101"})
    assert r["status"] == "pending_approval" and not [c for c in CALLS if c[0] == "mac_mail_send"]
    await actions.decide_approval(r["approval_id"], approve=True)
    assert [c for c in CALLS if c[0] == "mac_mail_send"][-1][1]["reply_to_id"] == "101"


@pytest.mark.anyio
async def test_free_slots_and_receptionist_booking_from_mac_calendar():
    tz = ZoneInfo("Europe/Rome")
    day = dt.datetime.now(tz).date() + dt.timedelta(days=1)
    at = lambda h: dt.datetime.combine(day, dt.time(h), tz).isoformat()
    EVENTS.append({"title": "Dentist", "start": at(9), "end": at(11), "allday": False, "calendar": "me@gmail.com"})
    slots = (await mailcal.free_slots(day.isoformat(), days=1, duration_minutes=30, limit=3))["slots"]
    assert slots[0]["start"] == at(11)
    t = public.new_ticket("call", phone="+391111111111")
    r = await public.run("book_appointment", {"ticket": t, "start": at(14), "name": "Marco"})
    assert r["booked"] and [c for c in CALLS if c[0] == "mac_calendar_create"]
    with pytest.raises(RuntimeError, match="taken"):
        await public.run("book_appointment", {"ticket": t, "start": at(10), "name": "Marco"})


@pytest.mark.anyio
async def test_sorting_flags_instead_of_hiding_mail():
    await mailcal.organize(["101"], add_labels=["JARVIS/Needs reply"])
    tool, args, _ = CALLS[-1]
    assert tool == "mac_mail_organize" and args.get("flag") == 1 and "move_to" not in args
