"""Router stub behavior (P1 skeleton: no Mistral calls)."""

import pytest

from colab.config import load_config
from colab.model import RouterIntent
from colab.router.mistral import route_transcript


def test_route_always_delegates_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # Prevent `.env` loading from re-introducing a real key.
    # Empty string must be treated as missing secret by `get_secret()`.
    monkeypatch.setenv("MISTRAL_API_KEY", "")
    load_config.cache_clear()
    decision = route_transcript("bonjour")
    assert decision.intent == RouterIntent.DELEGATE_AGENT
