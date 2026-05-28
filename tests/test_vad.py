"""Tests for energy VAD."""

from __future__ import annotations

import struct

from colab.audio.vad import _rms


def test_rms_silence_is_zero() -> None:
    chunk = struct.pack("4h", 0, 0, 0, 0)
    assert _rms(chunk) == 0.0


def test_rms_detects_signal() -> None:
    chunk = struct.pack("4h", 1000, -1000, 1000, -1000)
    assert _rms(chunk) > 0.0
