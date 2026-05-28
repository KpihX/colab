"""Voice activity detection — energy-based utterance segmentation."""

from __future__ import annotations

import struct
from collections.abc import AsyncIterator

from colab.audio.mic import iter_microphone
from colab.config import load_config


def _rms(chunk: bytes) -> float:
    count = len(chunk) // 2
    if count == 0:
        return 0.0
    samples = struct.unpack(f"{count}h", chunk)
    mean_sq = sum(s * s for s in samples) / count
    return mean_sq**0.5


class VoiceActivityDetector:
    """Detect speech start/end for one utterance at a time."""

    def __init__(
        self,
        *,
        sample_rate: int | None = None,
        speech_threshold: float | None = None,
        silence_ms: int | None = None,
        min_speech_ms: int | None = None,
        max_utterance_s: float | None = None,
    ) -> None:
        cfg = load_config().get("audio", {})
        self.sample_rate = sample_rate or int(cfg.get("sample_rate", 16000))
        self.speech_threshold = speech_threshold or float(cfg.get("speech_threshold", 450.0))
        self.silence_ms = silence_ms or int(cfg.get("silence_ms", 900))
        self.min_speech_ms = min_speech_ms or int(cfg.get("min_speech_ms", 250))
        self.max_utterance_s = max_utterance_s or float(cfg.get("max_utterance_s", 30.0))
        self.chunk_duration_ms = int(cfg.get("chunk_duration_ms", 30))

    async def capture_utterance(self) -> bytes | None:
        """Block until one utterance is captured, or None on empty/noise-only."""
        chunks: list[bytes] = []
        speech_started = False
        speech_ms = 0
        silence_ms = 0
        total_ms = 0

        async for chunk in iter_microphone(
            sample_rate=self.sample_rate,
            chunk_duration_ms=self.chunk_duration_ms,
        ):
            level = _rms(chunk)
            total_ms += self.chunk_duration_ms

            if not speech_started:
                if level >= self.speech_threshold:
                    speech_started = True
                    chunks.append(chunk)
                    speech_ms = self.chunk_duration_ms
                    silence_ms = 0
                continue

            chunks.append(chunk)
            if level >= self.speech_threshold:
                speech_ms += self.chunk_duration_ms
                silence_ms = 0
            else:
                silence_ms += self.chunk_duration_ms

            if speech_ms >= self.min_speech_ms and silence_ms >= self.silence_ms:
                break

            if total_ms >= int(self.max_utterance_s * 1000):
                break

        if not speech_started or speech_ms < self.min_speech_ms:
            return None
        return b"".join(chunks)

    async def iter_utterances(self) -> AsyncIterator[bytes]:
        """Continuously yield PCM utterances."""
        while True:
            utterance = await self.capture_utterance()
            if utterance:
                yield utterance
