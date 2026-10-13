"""Phone line: simulated Twilio webhooks (signed exactly like Twilio) against a mocked Twilio API."""
import json
import os
import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["JARVIS_NO_SUPERVISOR"] = "1"

from backend import actions, db, phone, secrets_store, voice  # noqa: E402

PUBLIC = "https://test-tunnel.trycloudflare.com"
TOKEN = "0123456789abcdef0123456789abcdef"
OWNER = "+393451234567"
TWILIO_NO = "+15005550006"
SENT = []


def twilio_api(req: httpx.Request) -> httpx.Response:
    body = parse_qs(req.content.decode()) if req.content else {}
    SENT.append((req.method, req.url.path, {k: v[0] for k, v in body.items()}, dict(req.url.params)))
    if req.url.path.endswith("/IncomingPhoneNumbers.json"):
        return httpx.Response(200, json={"incoming_phone_numbers": [{"sid": "PN123", "phone_number": TWILIO_NO}]})
    if req.url.path.endswith("/Calls.json"):
        return httpx.Response(201, json={"sid": "CAout"})
    if req.url.path.endswith("/Messages.json"):
        return httpx.Response(201, json={"sid": "SM1"})
    return httpx.Response(200, json={})


def eleven(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"ID3mp3", headers={"content-type": "audio/mpeg"})


class SlowBrain:
    def __init__(self):
        self.seen = []

    async def stream(self, *, conversation, text, instructions, **kw):
        import asyncio
        self.seen.append((text, instructions))
        await asyncio.sleep(0.3)
        yield {"type": "text", "delta": f"You said {text}."}
        yield {"type": "done"}


@pytest.fixture
def client(monkeypatch):
    db.init()
    phone._transport = httpx.MockTransport(twilio_api)
    voice._transport = httpx.MockTransport(eleven)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    secrets_store.set_secret("twilio_auth_token", TOKEN)
    db.set_setting("phone", {"enabled": True, "account_sid": "AC" + "0" * 32, "twilio_number": TWILIO_NO,
                             "owner_number": OWNER, "language": "en-GB"})
    phone.STATE.update(public_url=PUBLIC, webhooks="configured", configured_for=PUBLIC, error=None)
    brain = SlowBrain()
    phone.get_brain = lambda: brain
    SENT.clear()
    with TestClient(phone.public_app) as c:
        c.brain = brain
        yield c
    phone._transport = None
    voice._transport = None


def post(c, path, form):
    sig = phone.signature(PUBLIC + path, form, TOKEN)
    return c.post(path, data=form, headers={"X-Twilio-Signature": sig})


def test_bad_signature_rejected(client):
    r = client.post("/twilio/voice", data={"From": OWNER, "CallSid": "CA1"}, headers={"X-Twilio-Signature": "nope"})
    assert r.status_code == 403
    assert client.get("/api/status").status_code == 404      # nothing but /twilio is exposed


def test_stranger_is_refused(client):
    db.set_setting("receptionist", {**db.get_settings()["receptionist"], "answer_others": False})
    r = post(client, "/twilio/voice", {"From": "+391111111111", "CallSid": "CAx"})
    assert "not available" in r.text and "<Hangup/>" in r.text


def test_full_call_conversation(client):
    r = post(client, "/twilio/voice", {"From": OWNER, "To": TWILIO_NO, "CallSid": "CA1"})
    assert r.status_code == 200 and "<Gather" in r.text and f"{PUBLIC}/twilio/audio/" in r.text
    audio_url = r.text.split("<Play>")[1].split("</Play>")[0].replace(PUBLIC, "")
    assert client.get(audio_url).content == b"ID3mp3"

    r = post(client, "/twilio/voice/turn", {"From": OWNER, "CallSid": "CA1", "SpeechResult": "what time is it"})
    assert "/twilio/voice/wait?" in r.text
    wait = r.text.split("<Redirect method=\"POST\">")[1].split("</Redirect>")[0].replace("&amp;", "&")
    for _ in range(40):
        r = post(client, wait, {"From": OWNER, "CallSid": "CA1"})
        if "<Gather" in r.text:
            break
        wait = r.text.split("<Redirect method=\"POST\">")[1].split("</Redirect>")[0].replace("&amp;", "&")
        time.sleep(0.1)
    assert "<Gather" in r.text and "<Play>" in r.text
    text, instr = client.brain.seen[-1]
    assert text == "what time is it" and "PHONE CALL" in instr
    cid = phone.CALLS["CA1"]["cid"]
    msgs = db.q("SELECT role, text FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    assert msgs[0]["text"] == "what time is it" and "You said" in msgs[1]["text"]

    r = post(client, "/twilio/voice/turn", {"From": OWNER, "CallSid": "CA1", "SpeechResult": "Goodbye."})
    assert "<Hangup/>" in r.text


def test_voice_approval(client):
    post(client, "/twilio/voice", {"From": OWNER, "CallSid": "CA2"})
    cid = phone.CALLS["CA2"]["cid"]

    import asyncio
    async def never():
        await asyncio.sleep(30)
    loop_job = "job-approval"
    # A running job whose conversation has a pending browser action.
    async def setup():
        phone.JOBS[loop_job] = {"task": asyncio.create_task(never()), "cid": cid, "t": time.time()}
    client.portal.call(setup)
    aid = actions.create_approval("browser_click", {"element": "Buy now"}, kind="external", conversation_id=cid,
                                  reason="clicking looks consequential")
    r = post(client, f"/twilio/voice/wait?job={loop_job}&n=3", {"From": OWNER, "CallSid": "CA2"})
    assert "Say yes or no" not in r.text  # spoken via ElevenLabs audio, so check the gather target instead
    assert f"/twilio/voice/approve?job={loop_job}&amp;a={aid}" in r.text
    r = post(client, f"/twilio/voice/approve?job={loop_job}&a={aid}", {"From": OWNER, "CallSid": "CA2", "SpeechResult": "Yes, go ahead"})
    assert db.one("SELECT status FROM approvals WHERE id=?", (aid,))["status"] == "approved"
    assert "/twilio/voice/wait?" in r.text


def test_outbound_call_and_sms(client):
    import asyncio
    r = client.portal.call(phone.call_owner, "Your report is ready.")
    assert r["calling"] == OWNER
    call = [s for s in SENT if s[1].endswith("/Calls.json")][-1]
    assert call[2]["To"] == OWNER and call[2]["From"] == TWILIO_NO and call[2]["Url"].startswith(PUBLIC + "/twilio/voice/outbound?m=")
    m = call[2]["Url"].split("m=")[1]
    r = post(client, f"/twilio/voice/outbound?m={m}", {"From": TWILIO_NO, "To": OWNER, "CallSid": "CAout"})
    assert "<Gather" in r.text

    client.portal.call(phone.sms_owner, "Hello from JARVIS")
    sms = [s for s in SENT if s[1].endswith("/Messages.json")][-1]
    assert sms[2] == {"To": OWNER, "From": TWILIO_NO, "Body": "Hello from JARVIS"}


def test_inbound_sms_gets_a_reply(client):
    r = post(client, "/twilio/sms", {"From": OWNER, "To": TWILIO_NO, "Body": "are you there?"})
    assert r.status_code == 200 and "<Message" not in r.text
    for _ in range(40):
        replies = [s for s in SENT if s[1].endswith("/Messages.json")]
        if replies:
            break
        time.sleep(0.1)
    assert replies and replies[-1][2]["Body"] == "You said are you there?."
    assert "SMS" in client.brain.seen[-1][1]
    # strangers are ignored
    SENT.clear()
    post(client, "/twilio/sms", {"From": "+390000000000", "Body": "hi"})
    time.sleep(0.5)
    assert not [s for s in SENT if s[1].endswith("/Messages.json")]


def test_configure_webhooks(client):
    client.portal.call(phone.configure_webhooks, PUBLIC)
    upd = [s for s in SENT if s[1].endswith("/IncomingPhoneNumbers/PN123.json")][-1]
    assert upd[2]["VoiceUrl"] == PUBLIC + "/twilio/voice" and upd[2]["SmsUrl"] == PUBLIC + "/twilio/sms"


def test_signature_matches_twilio_reference():
    # Example from Twilio's security docs.
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234",
              "From": "+12349013030", "To": "+18005551212"}
    assert phone.signature(url, params, "12345") == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


class PublicBrain:
    """Stands in for the receptionist profile: books via the real public tool code path."""
    def __init__(self):
        self.seen = []

    async def stream(self, *, conversation, text, instructions, **kw):
        import re as _re
        self.seen.append((conversation, text, instructions))
        ticket = _re.search(r"ticket=\"(T[0-9a-f]+)\"", instructions).group(1)
        from backend import public
        await public.run("take_message", {"ticket": ticket, "name": "Marco", "message": text})
        yield {"type": "tool_start", "id": "t1", "name": "take_message", "input": {}}
        yield {"type": "text", "delta": "Thanks Marco, I've passed that on."}
        yield {"type": "done"}


def test_receptionist_answers_strangers_and_texts_owner(client, monkeypatch):
    from backend import public
    db.set_setting("receptionist", {**db.get_settings()["receptionist"], "answer_others": True, "business_name": "Kyvo Studio"})
    pb = PublicBrain()
    monkeypatch.setattr(public, "brain", lambda: pb)
    r = post(client, "/twilio/voice", {"From": "+391111111111", "To": TWILIO_NO, "CallSid": "CApub"})
    assert "<Gather" in r.text and phone.CALLS["CApub"]["public"]
    r = post(client, "/twilio/voice/turn", {"From": "+391111111111", "CallSid": "CApub", "SpeechResult": "please ask him to call me"})
    wait = r.text.split('<Redirect method="POST">')[1].split("</Redirect>")[0].replace("&amp;", "&")
    for _ in range(40):
        r = post(client, wait, {"From": "+391111111111", "CallSid": "CApub"})
        if "<Gather" in r.text:
            break
        wait = r.text.split('<Redirect method="POST">')[1].split("</Redirect>")[0].replace("&amp;", "&")
        time.sleep(0.05)
    conv, text, instr = pb.seen[-1]
    assert "NOT talking to" in instr and "Kyvo Studio" in instr and "PHONE CALL" in instr
    texts = [s[2] for s in SENT if s[1].endswith("/Messages.json")]
    assert texts and texts[-1]["To"] == OWNER and "Message from" in texts[-1]["Body"] and "+391111111111" in texts[-1]["Body"]
    # strangers can never approve things
    r = post(client, "/twilio/voice/approve?job=x&a=1", {"From": "+391111111111", "CallSid": "CApub", "SpeechResult": "yes"})
    assert "<Hangup/>" in r.text


def test_stranger_sms_needs_owner_yes(client, monkeypatch):
    from backend import public

    class Drafter:
        async def stream(self, *, conversation, text, instructions, **kw):
            yield {"type": "text", "delta": "Hi! We're open 9-18, want to book?"}
            yield {"type": "done"}
    monkeypatch.setattr(public, "brain", lambda: Drafter())
    db.set_setting("receptionist", {**db.get_settings()["receptionist"], "answer_others": True, "approve_by_text": True})
    SENT.clear()
    post(client, "/twilio/sms", {"From": "+392222222222", "To": TWILIO_NO, "Body": "are you open tomorrow?"})
    for _ in range(40):
        ap = db.one("SELECT * FROM approvals WHERE tool='text_message' AND status='pending' ORDER BY id DESC LIMIT 1")
        asked = [s for s in SENT if s[1].endswith("/Messages.json") and "needs your OK" in s[2]["Body"]]
        if ap and asked:
            break
        time.sleep(0.05)
    assert ap and asked and asked[-1][2]["To"] == OWNER
    assert not [s for s in SENT if s[1].endswith("/Messages.json") and s[2]["To"] == "+392222222222"]   # nothing sent yet
    post(client, "/twilio/sms", {"From": OWNER, "To": TWILIO_NO, "Body": f"YES {ap['id']}"})
    for _ in range(40):
        out = [s for s in SENT if s[1].endswith("/Messages.json") and s[2]["To"] == "+392222222222"]
        if out:
            break
        time.sleep(0.05)
    assert out and out[-1][2]["Body"].startswith("Hi! We're open")
    assert db.one("SELECT status FROM approvals WHERE id=?", (ap["id"],))["status"] == "executed"
