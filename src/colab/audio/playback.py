"""Local audio playback helpers."""

from __future__ import annotations

import struct
import threading
from typing import Any


class PcmPlayer:
    """Play float32 PCM chunks through the default output device."""

    def __init__(
        self,
        *,
        sample_rate: int = 24000,
        channels: int = 1,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._stop = threading.Event()
        self._pa: Any = None
        self._stream: Any = None

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def reset_stop(self) -> None:
        self._stop.clear()

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return
        try:
            import pyaudio
        except ImportError as exc:
            raise ImportError(
                "Playback requires PyAudio. Install with: uv sync --extra audio"
            ) from exc

        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
        )

    def write_pcm(self, pcm_bytes: bytes) -> bool:
        """Write one PCM chunk. Returns False if stop was requested."""
        if self._stop.is_set() or not pcm_bytes:
            return False
        self._ensure_stream()
        self._stream.write(pcm_bytes)
        return True

    @staticmethod
    def decode_float32(pcm_bytes: bytes) -> bytes:
        """Validate chunk is float32-aligned (passthrough for PyAudio)."""
        if len(pcm_bytes) % 4 != 0:
            raise ValueError("PCM chunk size must be multiple of 4 bytes (float32)")
        return pcm_bytes

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None


def rms_int16(chunk: bytes) -> float:
    count = len(chunk) // 2
    if count == 0:
        return 0.0
    samples = struct.unpack(f"{count}h", chunk)
    mean_sq = sum(s * s for s in samples) / count
    return mean_sq**0.5
