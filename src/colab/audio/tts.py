"""Text-to-speech — Mistral Voxtral TTS with streaming playback."""

from __future__ import annotations

import base64
import logging
import re
import threading

from colab.audio.playback import PcmPlayer
from colab.config import get_secret, load_config
from colab.exceptions import AudioNotReadyError, SecretsError

logger = logging.getLogger(__name__)

_PLAYER: TtsPlayer | None = None
_PLAYER_LOCK = threading.Lock()
_VOICE_ID_CACHE: str | None = None

_MARKDOWN_RE = re.compile(r"[*_`#\[\]()]+")


def _tts_enabled(*, require_listen: bool = False) -> bool:
    cfg = load_config().get("audio", {})
    if not cfg.get("tts_enabled", True):
        return False
    if require_listen and not cfg.get("enabled", False):
        return False
    return True


def listen_tts_enabled() -> bool:
    """TTS during `colab listen` (requires audio.enabled)."""
    return _tts_enabled(require_listen=True)


def _sanitize_for_speech(text: str) -> str:
    """Strip markdown-ish noise — Mistral TTS best practice."""
    cleaned = _MARKDOWN_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _resolve_voice_id() -> str:
    global _VOICE_ID_CACHE
    if _VOICE_ID_CACHE:
        return _VOICE_ID_CACHE

    cfg = load_config()
    voice = cfg.get("mistral", {}).get("tts_voice_id")
    if voice:
        _VOICE_ID_CACHE = str(voice)
        return _VOICE_ID_CACHE

    slug = cfg.get("mistral", {}).get("tts_voice_slug", "fr_marie_neutral")
    try:
        from mistralai.client import Mistral

        client = Mistral(api_key=get_secret("MISTRAL_API_KEY"))
        resp = client.audio.voices.list(limit=100)
        for item in resp.items:
            if getattr(item, "slug", None) == slug:
                _VOICE_ID_CACHE = str(item.id)
                return _VOICE_ID_CACHE
    except Exception as exc:  # pragma: no cover - network
        logger.warning("Could not resolve voice slug %s: %s", slug, exc)
    raise SecretsError(f"Set mistral.tts_voice_id in ~/.colab/config.yaml (slug {slug} not found)")


class TtsPlayer:
    """Stream Voxtral TTS and play locally with interrupt support."""

    def __init__(self) -> None:
        cfg = load_config().get("audio", {})
        self._output_rate = int(cfg.get("tts_sample_rate", 24000))
        self._player = PcmPlayer(sample_rate=self._output_rate)
        self._speaking = False
        self._lock = threading.Lock()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def stop_requested(self) -> bool:
        return self._player.stop_requested

    def stop_speaking(self) -> None:
        self._player.request_stop()

    def speak(self, text: str) -> bool:
        """Speak text. Returns False if interrupted before completion."""
        spoken = _sanitize_for_speech(text)
        if not spoken:
            return True
        if not _tts_enabled():
            logger.debug("TTS disabled — skipping playback")
            return True

        api_key = get_secret("MISTRAL_API_KEY")
        if not api_key:
            raise SecretsError("MISTRAL_API_KEY required for TTS")

        try:
            from mistralai.client import Mistral
        except ImportError as exc:
            raise AudioNotReadyError(
                "TTS requires mistralai. Install with: uv sync --extra audio"
            ) from exc

        cfg = load_config().get("mistral", {})
        model = cfg.get("tts_model", "voxtral-mini-tts-2603")
        voice_id = _resolve_voice_id()
        client = Mistral(api_key=api_key)

        with self._lock:
            self._speaking = True
            self._player.reset_stop()

        interrupted = False
        try:
            stream = client.audio.speech.complete(
                input=spoken,
                model=model,
                voice_id=voice_id,
                response_format="pcm",
                stream=True,
            )
            for event in stream:
                if self._player.stop_requested:
                    interrupted = True
                    break
                if getattr(event, "event", None) != "speech.audio.delta":
                    continue
                data = getattr(event, "data", None)
                if data is None or not getattr(data, "audio_data", None):
                    continue
                pcm = base64.b64decode(data.audio_data)
                if not self._player.write_pcm(PcmPlayer.decode_float32(pcm)):
                    interrupted = True
                    break
        finally:
            with self._lock:
                self._speaking = False
            self._player.close()
            self._player = PcmPlayer(sample_rate=self._output_rate)

        return not interrupted


def get_tts_player() -> TtsPlayer:
    global _PLAYER
    with _PLAYER_LOCK:
        if _PLAYER is None:
            _PLAYER = TtsPlayer()
        return _PLAYER


def speak(text: str) -> bool:
    """Module-level speak helper."""
    return get_tts_player().speak(text)


def stop_speaking() -> None:
    """Interrupt current playback."""
    get_tts_player().stop_speaking()
