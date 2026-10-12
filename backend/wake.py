"""'Hey JARVIS' wake word, detected locally with openWakeWord.

The JARVIS window streams 16 kHz mono audio over a local WebSocket (it already has
microphone permission). Detection runs here on the Mac; no audio leaves the computer and
nothing is recorded or stored. When the phrase is heard, the window is told to wake up.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

log = logging.getLogger("jarvis.wake")
FRAME = 1280          # 80 ms at 16 kHz, what openWakeWord expects
COOLDOWN_S = 2.5
STATE = {"clients": 0, "last_wake": None, "error": None}


def model_path() -> Path | None:
    try:
        import openwakeword
    except Exception as e:  # not installed
        STATE["error"] = f"Wake word engine isn't installed ({e}). Run the JARVIS updater or installer."
        return None
    p = Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
    if not p.exists():
        STATE["error"] = "The 'hey jarvis' model file is missing. Run the JARVIS installer again."
        return None
    return p


class Detector:
    def __init__(self, threshold: float = 0.5):
        import numpy as np
        from openwakeword.model import Model
        self.np = np
        path = model_path()
        if not path:
            raise RuntimeError(STATE["error"])
        self.model = Model(wakeword_model_paths=[str(path)])
        self.key = next(iter(self.model.models))
        self.threshold = threshold
        self.buf = np.zeros(0, dtype=np.int16)
        self.last = 0.0

    def feed(self, pcm16: bytes) -> float | None:
        """Feed raw little-endian int16 audio; returns the score when the wake word fires."""
        np = self.np
        self.buf = np.concatenate([self.buf, np.frombuffer(pcm16, dtype="<i2")])
        fired = None
        while len(self.buf) >= FRAME:
            frame, self.buf = self.buf[:FRAME], self.buf[FRAME:]
            score = float(self.model.predict(frame)[self.key])
            if score >= self.threshold and time.time() - self.last > COOLDOWN_S:
                self.last = time.time()
                self.model.reset()
                fired = score
        return fired


def available() -> bool:
    return model_path() is not None


async def serve(ws, threshold: float) -> None:
    """Run one WebSocket session: binary frames in, {"type": "wake"} out."""
    try:
        det = await asyncio.to_thread(Detector, threshold)
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
        return
    STATE["clients"] += 1
    STATE["error"] = None
    await ws.send_json({"type": "ready"})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                score = await asyncio.to_thread(det.feed, data)
                if score is not None:
                    STATE["last_wake"] = time.time()
                    log.info("wake word heard (%.2f)", score)
                    await ws.send_json({"type": "wake", "score": round(score, 3)})
            elif msg.get("text") == "reset":
                det.model.reset()
                det.buf = det.np.zeros(0, dtype=det.np.int16)
    finally:
        STATE["clients"] -= 1
