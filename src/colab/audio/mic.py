"""Microphone capture — async PCM16 mono chunks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


async def iter_microphone(
    *,
    sample_rate: int = 16000,
    chunk_duration_ms: int = 30,
) -> AsyncIterator[bytes]:
    """Yield microphone PCM chunks (pcm_s16le, mono).

    Requires optional `colab[audio]` (`PyAudio`).
    """
    try:
        import pyaudio
    except ImportError as exc:
        raise ImportError(
            "Microphone capture requires PyAudio. Install with: uv sync --extra audio"
        ) from exc

    chunk_samples = max(1, int(sample_rate * chunk_duration_ms / 1000))
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=chunk_samples,
    )
    loop = asyncio.get_running_loop()
    try:
        while True:
            data = await loop.run_in_executor(None, stream.read, chunk_samples, False)
            yield data
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
