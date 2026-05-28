"""Barge-in monitor — detect user speech during TTS playback."""

from __future__ import annotations

import asyncio

from colab.audio.mic import iter_microphone
from colab.audio.playback import rms_int16
from colab.config import load_config


async def wait_for_barge_in(player: object) -> bool:
    """Return True when sustained speech is detected on the microphone."""
    cfg = load_config().get("audio", {})
    sample_rate = int(cfg.get("sample_rate", 16000))
    chunk_ms = int(cfg.get("chunk_duration_ms", 30))
    threshold = float(cfg.get("speech_threshold", 450.0))
    barge_in_ms = int(cfg.get("barge_in_ms", 400))

    speech_ms = 0
    async for chunk in iter_microphone(sample_rate=sample_rate, chunk_duration_ms=chunk_ms):
        if getattr(player, "stop_requested", False):
            return False
        if rms_int16(chunk) >= threshold:
            speech_ms += chunk_ms
            if speech_ms >= barge_in_ms:
                return True
        else:
            speech_ms = 0
        await asyncio.sleep(0)
