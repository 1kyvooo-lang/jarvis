"""ElevenLabs calls checked against the documented request/response shapes (mocked network)."""
import asyncio

import httpx
import pytest

from backend import secrets_store, voice

seen = []


def handler(req: httpx.Request) -> httpx.Response:
    seen.append(req)
    if req.headers.get("xi-api-key") == "el-restricted":
        return httpx.Response(401, json={"detail": {"status": "missing_permissions",
                              "message": "The API key you used is missing the permission voices_read to execute this operation."}})
    if req.headers.get("xi-api-key") != "el-test-key":
        return httpx.Response(401, json={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
    if req.url.path == "/v1/speech-to-text":
        body = req.content
        assert b'name="model_id"' in body and b"scribe_v2" in body and b'name="file"' in body
        return httpx.Response(200, json={"language_code": "en", "text": "Open GitHub please.", "words": []})
    if req.url.path.startswith("/v1/text-to-speech/") and req.url.path.endswith("/stream"):
        assert req.url.params["output_format"] == "mp3_44100_128"
        return httpx.Response(200, content=b"ID3fake-mp3-bytes")
    if req.url.path == "/v1/voices":
        return httpx.Response(200, json={"voices": [{"voice_id": "abc", "name": "Jarvis-ish", "category": "cloned"}]})
    if req.url.path == "/v1/models":
        return httpx.Response(200, json=[{"model_id": "eleven_flash_v2_5", "name": "Multilingual v2", "can_do_text_to_speech": True},
                                         {"model_id": "scribe_v2", "name": "Scribe", "can_do_text_to_speech": False}])
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def mock(monkeypatch):
    voice._transport = httpx.MockTransport(handler)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test-key")
    seen.clear()
    yield
    voice._transport = None


def run(coro):
    return asyncio.run(coro)


def test_transcribe():
    assert run(voice.transcribe(b"x" * 3000, "speech.webm", "audio/webm")) == "Open GitHub please."
    assert seen[-1].url == "https://api.elevenlabs.io/v1/speech-to-text"


def test_speak_streams_mp3_with_default_voice():
    async def go():
        stream = await voice.speak("Good evening.", None, None)
        return b"".join([c async for c in stream])
    assert run(go()).startswith(b"ID3")
    assert seen[-1].url.path == f"/v1/text-to-speech/{voice.DEFAULT_VOICE}/stream"
    import json
    assert json.loads(seen[-1].content) == {"text": "Good evening.", "model_id": "eleven_flash_v2_5", "voice_settings": voice.VOICE_SETTINGS}


def test_voices_models_and_bad_key(monkeypatch):
    assert run(voice.voices())[0]["name"] == "Jarvis-ish"
    assert [m["model_id"] for m in run(voice.models())] == ["eleven_flash_v2_5"]
    with pytest.raises(voice.VoiceError) as e:
        run(voice.check_key("wrong"))
    assert e.value.status == 401 and "accept" in str(e.value)


def test_restricted_key_is_accepted_with_warning():
    r = run(voice.check_key("el-restricted"))
    assert r["warning"] and "voices_read" in r["warning"]
