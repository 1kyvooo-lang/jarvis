"""JARVIS manners in the instructions, and the voice fallback."""
import os

import httpx
import pytest

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import chat, db, voice  # noqa: E402


def test_jarvis_manner_and_address():
    db.init()
    s = db.get_settings()
    text = chat.instructions(s, "hi", "voice")
    assert "British" in text and "'sir'" in text and "TALKING" in text
    s["personality"] = {"style": "jarvis", "address": "boss"}
    assert "'boss'" in chat.instructions(s, "hi")
    s["personality"] = {"style": "friendly", "address": "sir"}
    assert "British" not in chat.instructions(s, "hi")


@pytest.mark.anyio
async def test_default_voice_falls_back(monkeypatch):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if voice.DEFAULT_VOICE in req.url.path:
            return httpx.Response(404, json={"detail": {"status": "voice_not_found", "message": "not found"}})
        return httpx.Response(200, content=b"ID3")
    voice._transport = httpx.MockTransport(handler)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    try:
        audio = b"".join([c async for c in await voice.speak("Good evening, sir.", None, None)])
    finally:
        voice._transport = None
    assert audio == b"ID3" and voice.FALLBACK_VOICE in calls[-1]
