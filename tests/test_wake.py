"""Wake word: the WebSocket detects 'hey jarvis' in streamed audio and refuses other origins."""
import os
import shutil
import subprocess
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import main, wake  # noqa: E402

pytestmark = pytest.mark.skipif(not wake.available() or not shutil.which("espeak-ng"),
                                reason="needs openwakeword and espeak-ng")


def speech(text, tmp_path) -> bytes:
    path = tmp_path / "s.wav"
    subprocess.run(["espeak-ng", "-v", "en-gb", "-s", "150", text, "-w", str(path)], check=True)
    with wave.open(str(path)) as w:
        sr, x = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    from scipy.signal import resample_poly
    x = resample_poly(x, 16000, sr)
    pad = np.zeros(16000, np.float32)
    return np.concatenate([pad, x, pad, pad]).astype("<i2").tobytes()




def test_detects_hey_jarvis(tmp_path):
    audio = speech("hey jarvis", tmp_path)
    with TestClient(main.app) as c, c.websocket_connect("/api/wake/ws", headers={"origin": "http://127.0.0.1:8000"}) as ws:
        assert ws.receive_json()["type"] == "ready"
        for i in range(0, len(audio), 5120):
            ws.send_bytes(audio[i:i + 5120])
        msg = ws.receive_json()
        assert msg["type"] == "wake" and msg["score"] >= 0.5


def test_ignores_other_speech(tmp_path):
    det = wake.Detector(0.5)
    audio = speech("what is the weather like today in london", tmp_path)
    assert all(det.feed(audio[i:i + 5120]) is None for i in range(0, len(audio), 5120))


def test_rejects_foreign_origin():
    from starlette.websockets import WebSocketDisconnect
    with TestClient(main.app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/wake/ws", headers={"origin": "https://evil.example"}) as ws:
                ws.receive_json()
