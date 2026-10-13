"""Reminders and the morning briefing, delivered through a mocked Twilio."""
import datetime as dt
import os
from urllib.parse import parse_qs

import httpx
import pytest

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import actions, db, main, phone, routines, secrets_store  # noqa: E402

SENT = []


def twilio(req: httpx.Request) -> httpx.Response:
    SENT.append((req.url.path, {k: v[0] for k, v in parse_qs(req.content.decode()).items()}))
    return httpx.Response(201, json={"sid": "X"})


@pytest.fixture(autouse=True)
def setup():
    db.init()
    db.ex("DELETE FROM reminders")
    phone._transport = httpx.MockTransport(twilio)
    secrets_store.set_secret("twilio_auth_token", "0" * 32)
    db.set_setting("phone", {"enabled": True, "account_sid": "AC" + "0" * 32, "twilio_number": "+15005550006",
                             "owner_number": "+393451234567", "language": "en-GB"})
    SENT.clear()
    yield
    phone._transport = None


@pytest.mark.anyio
async def test_reminder_is_texted_once_when_due():
    soon = (dt.datetime.now().astimezone() + dt.timedelta(seconds=1)).isoformat()
    r = await actions.run_tool("remind_me", {"text": "call Marco", "at": soon})
    assert r["status"] == "ok" and r["output"]["via"] == "text"
    assert await routines.reminders_tick() == 0            # not due yet
    db.ex("UPDATE reminders SET due_at=? WHERE id=?", ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)).isoformat(timespec="seconds"), r["output"]["id"]))
    assert await routines.reminders_tick() == 1
    assert await routines.reminders_tick() == 0            # never twice
    assert SENT[-1][1]["Body"] == "Reminder: call Marco" and SENT[-1][1]["To"] == "+393451234567"


@pytest.mark.anyio
async def test_reminder_in_the_past_is_refused_and_cancel_works():
    r = await actions.run_tool("remind_me", {"text": "x", "at": "2001-01-01T10:00:00"})
    assert r["status"] == "error" and "passed" in r["error"]
    later = (dt.datetime.now().astimezone() + dt.timedelta(hours=2)).isoformat()
    rid = (await actions.run_tool("remind_me", {"text": "y", "at": later}))["output"]["id"]
    assert (await actions.run_tool("cancel_reminder", {"reminder_id": rid}))["output"]["cancelled"]
    assert not routines.list_reminders()


@pytest.mark.anyio
async def test_briefing_sends_once_a_day(monkeypatch):
    class Brain:
        async def stream(self, *, conversation, text, instructions, **kw):
            assert '"tasks"' in text and "SMS" in instructions
            yield {"type": "text", "delta": "Morning! Light day: 1 task, nothing waiting."}
            yield {"type": "done"}
    monkeypatch.setattr(main, "brain_override", Brain())
    now = dt.datetime.now().astimezone()
    db.set_setting("briefing", {"enabled": True, "time": now.strftime("%H:%M"), "days": [1, 2, 3, 4, 5, 6, 7], "via": "text"})
    actions.create_task("Send invoice")
    assert await routines.briefing_tick() is True
    assert await routines.briefing_tick() is False          # already sent today
    assert SENT[-1][1]["Body"].startswith("Morning! Light day")


@pytest.mark.anyio
async def test_briefing_falls_back_without_ai(monkeypatch):
    class Broken:
        async def stream(self, **kw):
            raise RuntimeError("Hermes down")
            yield
    monkeypatch.setattr(main, "brain_override", Broken())
    r = await routines.send_briefing("text")
    assert r["text"].startswith("Good morning") and SENT
