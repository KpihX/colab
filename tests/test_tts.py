"""Tests for TTS text sanitization."""

from __future__ import annotations

from colab.audio.tts import _sanitize_for_speech


def test_sanitize_strips_markdown() -> None:
    assert _sanitize_for_speech("**Bonjour** _monde_") == "Bonjour monde"


def test_sanitize_collapses_whitespace() -> None:
    assert _sanitize_for_speech("  hello   world  ") == "hello world"
