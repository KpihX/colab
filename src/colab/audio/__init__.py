"""Audio pipeline — STT, TTS, VAD (P6+)."""

from colab.audio.stt import transcribe_pcm
from colab.audio.tts import get_tts_player, listen_tts_enabled, speak, stop_speaking
from colab.audio.vad import VoiceActivityDetector

__all__ = [
    "VoiceActivityDetector",
    "get_tts_player",
    "listen_tts_enabled",
    "speak",
    "stop_speaking",
    "transcribe_pcm",
]
