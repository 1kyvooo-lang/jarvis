"""Twilio phone line for JARVIS: you can call or text him, and he can call or text you.

Only your own phone number is served; every other caller is turned away. Twilio reaches
JARVIS through a separate, minimal web server (only the /twilio routes) exposed by a
Cloudflare quick tunnel while your Mac is on. Every webhook must carry a valid Twilio
signature made with your Auth Token.

Call flow (Twilio <Gather input="speech"> turns):
  /twilio/voice ─▶ greeting + listen ─▶ /twilio/voice/turn (your words)
      ─▶ JARVIS works in the background ─▶ /twilio/voice/wait polls every ~2s
      ─▶ answer spoken (ElevenLabs voice) + listen again
  If an action needs approval mid-call, JARVIS asks and you answer "yes" or "no".
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import html
import logging
import re
import secrets
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import actions, chat, db, secrets_store, voice

log = logging.getLogger("jarvis.phone")
API = "https://api.twilio.com/2010-04-01"
_transport: httpx.AsyncBaseTransport | None = None     # tests inject a mock Twilio
get_brain: Callable[[], Any] | None = None              # set by backend.main

STATE: dict[str, Any] = {"public_url": None, "webhooks": None, "error": None, "configured_for": None}
AUDIO: dict[str, tuple[bytes, float]] = {}
JOBS: dict[str, dict] = {}
CALLS: dict[str, dict] = {}
OUTBOUND: dict[str, str] = {}

HANG_UP = re.compile(r"^\s*(bye|goodbye|good bye|bye bye|end (the )?call|hang up|that'?s all|ciao)[\s.!]*$", re.I)
YES = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|approve|approved|go ahead|do it|confirm|sì|si)\b", re.I)
NO = re.compile(r"\b(no|nope|don'?t|deny|denied|cancel|stop|negative)\b", re.I)


# ---------------------------------------------------------------- config

def cfg() -> dict:
    p = dict(db.get_settings().get("phone") or {})
    p["auth_token"] = secrets_store.get_secret("twilio_auth_token", env="TWILIO_AUTH_TOKEN")[0] or ""
    p["account_sid"] = (p.get("account_sid") or "").strip()
    p["twilio_number"] = normalize(p.get("twilio_number") or "")
    p["owner_number"] = normalize(p.get("owner_number") or "")
    return p


def configured(c: dict | None = None) -> bool:
    c = c or cfg()
    return bool(c.get("enabled") and c["account_sid"] and c["auth_token"] and c["twilio_number"] and c["owner_number"])


def normalize(num: str) -> str:
    n = re.sub(r"[^\d+]", "", num or "")
    if n.startswith("00"):
        n = "+" + n[2:]
    return n


def status() -> dict:
    c = cfg()
    return {"enabled": bool(c.get("enabled")), "configured": configured(c), "public_url": STATE["public_url"],
            "webhooks": STATE["webhooks"], "error": STATE["error"],
            "token_hint": secrets_store.mask(c["auth_token"]) if c["auth_token"] else None}


# ---------------------------------------------------------------- Twilio REST

async def _api(method: str, path: str, data: dict | None = None, params: dict | None = None) -> dict:
    c = cfg()
    if not (c["account_sid"] and c["auth_token"]):
        raise RuntimeError("Twilio isn't set up. Add your Account SID and Auth Token in Settings → Phone.")
    async with httpx.AsyncClient(transport=_transport, timeout=20, auth=(c["account_sid"], c["auth_token"])) as cl:
        r = await cl.request(method, f"{API}/Accounts/{c['account_sid']}{path}", data=data, params=params)
    if r.status_code >= 400:
        try:
            j = r.json()
            msg = j.get("message") or r.text
        except ValueError:
            msg = r.text
        if r.status_code == 401:
            msg = "Twilio rejected the Account SID / Auth Token."
        raise RuntimeError(f"Twilio error {r.status_code}: {msg}"[:300])
    return r.json() if r.content else {}


async def configure_webhooks(public_url: str) -> dict:
    """Point your Twilio number's voice and SMS webhooks at this Mac's tunnel."""
    c = cfg()
    found = await _api("GET", "/IncomingPhoneNumbers.json", params={"PhoneNumber": c["twilio_number"]})
    nums = found.get("incoming_phone_numbers") or []
    if not nums:
        raise RuntimeError(f"{c['twilio_number']} isn't a number in this Twilio account.")
    sid = nums[0]["sid"]
    await _api("POST", f"/IncomingPhoneNumbers/{sid}.json", data={
        "VoiceUrl": f"{public_url}/twilio/voice", "VoiceMethod": "POST",
        "SmsUrl": f"{public_url}/twilio/sms", "SmsMethod": "POST"})
    STATE.update(webhooks="configured", configured_for=public_url, error=None)
    db.log_activity("Phone number webhooks pointed at this Mac", "info", tool="phone", source="system",
                    result={"number": c["twilio_number"]})
    return {"number_sid": sid}


async def call_owner(message: str = "") -> dict:
    c = cfg()
    if not configured(c):
        raise RuntimeError("The phone line isn't set up yet (Settings → Phone).")
    if not STATE["public_url"]:
        raise RuntimeError("The phone line isn't online yet (tunnel starting). Try again in a moment.")
    mid = secrets.token_urlsafe(9)
    OUTBOUND[mid] = message.strip() or "Hello, it's JARVIS. What can I do for you?"
    url = f"{STATE['public_url']}/twilio/voice/outbound?{urlencode({'m': mid})}"
    r = await _api("POST", "/Calls.json", data={"To": c["owner_number"], "From": c["twilio_number"], "Url": url,
                                                "Method": "POST"})
    db.log_activity(f"Calling you: {OUTBOUND[mid][:80]}", "ok", tool="call_me", approval="auto", source="assistant")
    return {"calling": c["owner_number"], "call_sid": r.get("sid")}


async def sms_owner(body: str) -> dict:
    c = cfg()
    if not configured(c):
        raise RuntimeError("The phone line isn't set up yet (Settings → Phone).")
    body = body.strip()
    if not body:
        raise RuntimeError("Empty message")
    sids = []
    for i in range(0, len(body), 1500):
        r = await _api("POST", "/Messages.json", data={"To": c["owner_number"], "From": c["twilio_number"],
                                                       "Body": body[i:i + 1500]})
        sids.append(r.get("sid"))
    db.log_activity(f"Texted you: {body[:80]}", "ok", tool="send_sms", approval="auto", source="assistant")
    return {"sent_to": c["owner_number"], "messages": len(sids)}


# ---------------------------------------------------------------- signatures & TwiML

def signature(url: str, params: dict[str, str], token: str) -> str:
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def _twiml(body: str) -> Response:
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="text/xml")


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


async def _say(text: str) -> str:
    """Speak with the ElevenLabs voice if available, else Twilio's built-in voice."""
    text = re.sub(r"[*_#`>]", "", text).strip()[:2500]
    if not text:
        return ""
    if voice.key() and STATE["public_url"]:
        try:
            v = db.get_settings().get("voice") or {}
            stream = await voice.speak(text, v.get("voice_id") or None, v.get("tts_model") or None)
            audio = b"".join([chunk async for chunk in stream])
            aid = secrets.token_urlsafe(16)
            AUDIO[aid] = (audio, time.time() + 900)
            for k in [k for k, (_, exp) in AUDIO.items() if exp < time.time()]:
                AUDIO.pop(k, None)
            return f"<Play>{_esc(STATE['public_url'])}/twilio/audio/{aid}.mp3</Play>"
        except Exception as e:
            log.warning("ElevenLabs failed for phone audio, using Twilio voice: %s", e)
    c = cfg()
    return f'<Say voice="{_esc(c.get("say_voice") or "Polly.Brian")}" language="{_esc(c.get("language") or "en-GB")}">{_esc(text)}</Say>'


def _gather(prompt_xml: str, action: str) -> str:
    c = cfg()
    return (f'<Gather input="speech" action="{_esc(action)}" method="POST" speechTimeout="auto" '
            f'actionOnEmptyResult="true" language="{_esc(c.get("language") or "en-GB")}">{prompt_xml}</Gather>'
            f'<Redirect method="POST">/twilio/voice/turn</Redirect>')


# ---------------------------------------------------------------- call handling

def _new_call(call_sid: str, outbound: bool) -> dict:
    when = dt.datetime.now().strftime("%d %b %H:%M")
    conv = chat.create_conversation(f"{'Call from JARVIS' if outbound else 'Phone call'} · {when}")
    CALLS[call_sid] = {"cid": conv["id"], "started": time.time()}
    db.log_activity(("JARVIS called you" if outbound else "You called JARVIS") + " — call connected", "info",
                    tool="phone", source="phone")
    return CALLS[call_sid]


def _start_job(cid: str, text: str, channel: str) -> str:
    job = uuid.uuid4().hex[:12]
    brain = get_brain() if get_brain else None
    JOBS[job] = {"task": asyncio.create_task(chat.ask(cid, text, brain, channel)), "cid": cid, "t": time.time()}
    for k in [k for k, j in JOBS.items() if time.time() - j["t"] > 3600]:
        JOBS.pop(k, None)
    return job


async def _wait_response(job: str, n: int) -> Response:
    j = JOBS.get(job)
    if not j:
        return _twiml(_gather(await _say("Sorry, I lost track of that. What were you saying?"), "/twilio/voice/turn"))
    if j["task"].done():
        JOBS.pop(job, None)
        try:
            _, reply = j["task"].result()
        except Exception as e:
            reply = f"Sorry, something went wrong: {e}"[:200]
        return _twiml(_gather(await _say(reply or "Done."), "/twilio/voice/turn"))
    ap = db.one("SELECT * FROM approvals WHERE conversation_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (j["cid"],))
    if ap and ap["kind"] != "agent":
        what = re.sub(r"[_(){}\[\]\"]", " ", ap["summary"])[:160]
        prompt = await _say(f"I need your OK to run {what}. Say yes or no.")
        return _twiml(_gather(prompt, f"/twilio/voice/approve?{urlencode({'job': job, 'a': ap['id']})}"))
    filler = ""
    if n == 1:
        filler = await _say("One moment.")
    elif n and n % 10 == 0:
        filler = await _say("Still working on it.")
    return _twiml(f'{filler}<Pause length="2"/><Redirect method="POST">/twilio/voice/wait?{urlencode({"job": job, "n": n + 1})}</Redirect>')


# ---------------------------------------------------------------- public web app (exposed via the tunnel)

public_app = FastAPI(title="JARVIS phone", docs_url=None, redoc_url=None, openapi_url=None)


@public_app.middleware("http")
async def verify_twilio(request: Request, call_next):
    path = request.url.path
    if request.method == "GET" and (path.startswith("/twilio/audio/") or path == "/twilio/health"):
        return await call_next(request)               # unguessable, short-lived audio ids
    if not path.startswith("/twilio/") or request.method != "POST":
        return JSONResponse({"detail": "not found"}, status_code=404)
    c = cfg()
    if not configured(c) or not STATE["public_url"]:
        return _twiml(await _say("JARVIS is not available right now.") + "<Hangup/>")
    form = dict((await request.form()).items())
    url = STATE["public_url"] + path + (f"?{request.url.query}" if request.url.query else "")
    expected = signature(url, {k: str(v) for k, v in form.items()}, c["auth_token"])
    if not hmac.compare_digest(expected, request.headers.get("X-Twilio-Signature", "")):
        log.warning("rejected request with bad Twilio signature: %s", path)
        return JSONResponse({"detail": "bad signature"}, status_code=403)
    request.state.form = form
    return await call_next(request)


def _owner_only(form: dict, field: str = "From") -> bool:
    return normalize(form.get(field, "")) == cfg()["owner_number"]


@public_app.get("/twilio/health")
async def health():
    return {"ok": True}


@public_app.post("/twilio/voice")
async def inbound_call(request: Request):
    f = request.state.form
    if not _owner_only(f):
        db.log_activity(f"Refused a call from {f.get('From', 'unknown')}", "denied", tool="phone", source="phone")
        return _twiml('<Say voice="Polly.Brian">Sorry, this line is not available.</Say><Hangup/>')
    if db.get_settings().get("emergency_stop"):
        return _twiml(await _say("JARVIS is on emergency stop. Release it on your Mac first.") + "<Hangup/>")
    _new_call(f.get("CallSid", ""), outbound=False)
    name = db.get_settings().get("user_name") or ""
    hello = f"Hello{(' ' + name) if name else ''}. JARVIS here. How can I help?"
    return _twiml(_gather(await _say(hello), "/twilio/voice/turn"))


@public_app.post("/twilio/voice/outbound")
async def outbound_answered(request: Request):
    f = request.state.form
    if not _owner_only(f, "To"):
        return _twiml("<Hangup/>")
    _new_call(f.get("CallSid", ""), outbound=True)
    msg = OUTBOUND.pop(request.query_params.get("m", ""), "Hello, it's JARVIS.")
    return _twiml(_gather(await _say(msg), "/twilio/voice/turn"))


@public_app.post("/twilio/voice/turn")
async def call_turn(request: Request):
    f = request.state.form
    if not (_owner_only(f) or _owner_only(f, "To")):
        return _twiml("<Hangup/>")
    call = CALLS.get(f.get("CallSid", "")) or _new_call(f.get("CallSid", ""), outbound=False)
    said = (f.get("SpeechResult") or "").strip()
    if not said:
        return _twiml(_gather(await _say("I'm listening."), "/twilio/voice/turn"))
    if HANG_UP.match(said):
        CALLS.pop(f.get("CallSid", ""), None)
        return _twiml(await _say("Goodbye.") + "<Hangup/>")
    job = _start_job(call["cid"], said, "phone")
    return _twiml(f'<Redirect method="POST">/twilio/voice/wait?{urlencode({"job": job, "n": 0})}</Redirect>')


@public_app.post("/twilio/voice/wait")
async def call_wait(request: Request):
    q = request.query_params
    return await _wait_response(q.get("job", ""), int(q.get("n", "0") or 0))


@public_app.post("/twilio/voice/approve")
async def call_approve(request: Request):
    f, q = request.state.form, request.query_params
    said = (f.get("SpeechResult") or "").strip()
    aid = int(q.get("a", "0") or 0)
    yes, no = bool(YES.search(said)), bool(NO.search(said))
    if yes == no:  # unclear or empty: ask again via the wait loop
        return await _wait_response(q.get("job", ""), 1)
    try:
        await actions.decide_approval(aid, approve=yes)
    except ValueError:
        pass  # already decided in the app
    prefix = await _say("Okay, doing it." if yes else "Okay, I won't.")
    return _twiml(f'{prefix}<Redirect method="POST">/twilio/voice/wait?{urlencode({"job": q.get("job", ""), "n": 2})}</Redirect>')


@public_app.post("/twilio/sms")
async def inbound_sms(request: Request):
    f = request.state.form
    if not _owner_only(f):
        db.log_activity(f"Ignored a text from {f.get('From', 'unknown')}", "denied", tool="phone", source="phone")
        return _twiml("")
    body = (f.get("Body") or "").strip()
    if body:
        asyncio.create_task(_sms_turn(body))
    return _twiml("")


async def _sms_turn(body: str) -> None:
    s = db.get_settings()
    cid = (s.get("phone") or {}).get("sms_conversation")
    if not cid or not db.one("SELECT id FROM conversations WHERE id=?", (cid,)):
        cid = chat.create_conversation("Text messages")["id"]
        db.set_setting("phone", {**(s.get("phone") or {}), "sms_conversation": cid})
    db.log_activity(f"Text from you: {body[:80]}", "info", tool="phone", source="phone")
    try:
        _, reply = await chat.ask(cid, body, get_brain() if get_brain else None, "sms")
        await sms_owner(reply or "Done.")
    except Exception as e:
        log.exception("SMS turn failed")
        db.log_activity("Couldn't answer your text", "error", tool="phone", error=str(e)[:300])


@public_app.get("/twilio/audio/{aid}.mp3")
async def audio(aid: str):
    item = AUDIO.get(aid)
    if not item or item[1] < time.time():
        return Response(status_code=404)
    return Response(item[0], media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
