"""ElevenLabs voice: Scribe speech-to-text and streaming text-to-speech.

The API key stays in the backend (Keychain); the browser only ever talks to /api/voice/*.
"""
from __future__ import annotations

import httpx

from . import secrets_store

BASE = "https://api.elevenlabs.io"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # "George" — the voice used in ElevenLabs' own examples
DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
DEFAULT_STT_MODEL = "scribe_v2"
_transport: httpx.AsyncBaseTransport | None = None  # tests inject a mock transport


def _client(**kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport, **kw)


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def key() -> str | None:
    return secrets_store.get_secret("elevenlabs_api_key", env="ELEVENLABS_API_KEY")[0]


def _headers(k: str | None = None) -> dict:
    k = k or key()
    if not k:
        raise VoiceError("Add your ElevenLabs API key in Settings → Voice.", 412)
    return {"xi-api-key": k}


def _detail(r: httpx.Response) -> tuple[str, str]:
    """(status, message) from an ElevenLabs error body."""
    try:
        d = r.json().get("detail")
    except Exception:
        return "", r.text[:200]
    if isinstance(d, dict):
        return str(d.get("status") or ""), str(d.get("message") or d.get("status") or "")
    return "", str(d or "")


def _explain(r: httpx.Response) -> VoiceError:
    status, message = _detail(r)
    if r.status_code == 401 and "permission" in (status + message).lower():
        return VoiceError(f"Your ElevenLabs key is missing a permission: {message} "
                          "Edit the key on elevenlabs.io (or create a new one with Text to Speech, Speech to Text, "
                          "Voices and Models allowed).", 403)
    if r.status_code == 401:
        return VoiceError("ElevenLabs didn't accept this key. Copy it again from elevenlabs.io → Developers → "
                          "API keys (the whole key, no spaces) and paste it here.", 401)
    if r.status_code == 429:
        return VoiceError("ElevenLabs rate limit or quota reached.", 429)
    return VoiceError(f"ElevenLabs error {r.status_code}: {message}", 502)


async def check_key(k: str) -> dict:
    """Accept any genuine key. A key restricted from listing voices still works for speech."""
    async with _client(timeout=15) as c:
        r = await c.get(f"{BASE}/v1/voices", headers=_headers(k))
    if r.status_code == 200:
        return {"voices": len(r.json().get("voices", [])), "warning": None}
    err = _explain(r)
    if err.status == 403:  # real key, just restricted
        return {"voices": 0, "warning": str(err)}
    raise err


async def voices() -> list[dict]:
    async with _client(timeout=15) as c:
        r = await c.get(f"{BASE}/v1/voices", headers=_headers())
    if r.status_code != 200:
        raise _explain(r)
    return [{"voice_id": v.get("voice_id"), "name": v.get("name"), "category": v.get("category"),
             "labels": v.get("labels") or {}, "preview_url": v.get("preview_url")}
            for v in r.json().get("voices", [])]


async def models() -> list[dict]:
    async with _client(timeout=15) as c:
        r = await c.get(f"{BASE}/v1/models", headers=_headers())
    if r.status_code != 200:
        raise _explain(r)
    return [{"model_id": m.get("model_id"), "name": m.get("name")} for m in r.json()
            if m.get("can_do_text_to_speech", True)]


async def transcribe(audio: bytes, filename: str, content_type: str, model_id: str = DEFAULT_STT_MODEL,
                     language: str | None = None) -> str:
    data = {"model_id": model_id or DEFAULT_STT_MODEL}
    if language:
        data["language_code"] = language
    async with _client(timeout=60) as c:
        r = await c.post(f"{BASE}/v1/speech-to-text", headers=_headers(), data=data,
                         files={"file": (filename, audio, content_type or "application/octet-stream")})
    if r.status_code != 200:
        raise _explain(r)
    return (r.json().get("text") or "").strip()


async def speak(text: str, voice_id: str | None, model_id: str | None):
    """Stream MP3 bytes. Raises VoiceError before the first chunk if ElevenLabs refuses."""
    headers = _headers()
    body = {"text": text[:5000], "model_id": model_id or DEFAULT_TTS_MODEL}
    client = _client(timeout=httpx.Timeout(20, read=60))
    req = client.build_request("POST", f"{BASE}/v1/text-to-speech/{voice_id or DEFAULT_VOICE}/stream",
                               params={"output_format": "mp3_44100_128"}, headers=headers, json=body)
    r = await client.send(req, stream=True)
    if r.status_code != 200:
        await r.aread()
        await client.aclose()
        raise _explain(r)

    async def gen():
        try:
            async for chunk in r.aiter_bytes():
                yield chunk
        finally:
            await r.aclose()
            await client.aclose()
    return gen()
