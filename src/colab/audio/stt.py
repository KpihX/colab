"""Speech-to-text — Mistral Voxtral Realtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from colab.config import get_secret, load_config
from colab.exceptions import AudioNotReadyError, SecretsError


def _audio_deps_available() -> bool:
    try:
        import mistralai.client  # noqa: F401

        return True
    except ImportError:
        return False


async def _bytes_iter(pcm: bytes, *, chunk_bytes: int = 960) -> AsyncIterator[bytes]:
    for offset in range(0, len(pcm), chunk_bytes):
        yield pcm[offset : offset + chunk_bytes]
        await asyncio.sleep(0)


async def transcribe_pcm(pcm: bytes) -> str:
    """Transcribe one utterance (pcm_s16le mono 16kHz) via Voxtral Realtime."""
    if not _audio_deps_available():
        raise AudioNotReadyError(
            "STT requires mistralai[realtime]. Install with: uv sync --extra audio"
        )

    api_key = get_secret("MISTRAL_API_KEY")
    if not api_key:
        raise SecretsError("MISTRAL_API_KEY required for STT")

    cfg = load_config().get("mistral", {})
    model = cfg.get("stt_model", "voxtral-mini-transcribe-realtime-2602")
    sample_rate = int(load_config().get("audio", {}).get("sample_rate", 16000))
    delay_ms = int(load_config().get("audio", {}).get("target_streaming_delay_ms", 480))

    from mistralai.client import Mistral
    from mistralai.client.models import (
        AudioFormat,
        TranscriptionStreamDone,
        TranscriptionStreamTextDelta,
    )

    client = Mistral(api_key=api_key)
    audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=sample_rate)

    parts: list[str] = []
    async for event in client.audio.realtime.transcribe_stream(
        audio_stream=_bytes_iter(pcm),
        model=model,
        audio_format=audio_format,
        target_streaming_delay_ms=delay_ms,
    ):
        if isinstance(event, TranscriptionStreamTextDelta):
            parts.append(event.text)
        elif isinstance(event, TranscriptionStreamDone):
            break

    return "".join(parts).strip()


def transcribe_stream() -> str:
    """Sync wrapper — prefer async transcribe_pcm in orchestrator."""
    raise AudioNotReadyError("Use transcribe_pcm() from the async listen loop")


async def transcribe_file(path: str) -> str:
    """Transcribe a raw PCM file (debug helper)."""
    from pathlib import Path

    data = Path(path).read_bytes()
    return await transcribe_pcm(data)


def iter_glossary_terms() -> Iterable[str]:
    """Load optional STT biasing terms from glossary file."""
    from pathlib import Path

    cfg = load_config().get("paths", {})
    glossary = Path(str(cfg.get("glossary_file", "~/.colab/glossary.yaml"))).expanduser()
    if not glossary.exists():
        return []
    import yaml

    raw = yaml.safe_load(glossary.read_text(encoding="utf-8")) or {}
    terms = raw.get("terms", [])
    if isinstance(terms, list):
        return [str(t) for t in terms if t]
    return []
