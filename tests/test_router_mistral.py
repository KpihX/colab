"""Mistral router tests with mocked API (P4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from colab.config import load_config
from colab.model import MetaAction, MetaCatalog, RouterDecision, RouterIntent
from colab.router.mistral import _build_router_json_schema, _catalog_summary, route_transcript

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_httpx_client(response_json: object, status: int = 200) -> MagicMock:
    """Build a mock `httpx.Client` that returns a given JSON response."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status
    mock_resp.json.return_value = response_json
    mock_resp.raise_for_status.return_value = None

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_resp
    return mock_client


def _fake_mistral_decision(
    intent: str,
    confidence: float = 0.92,
    simple_reply: str | None = None,
    meta_action_id: str | None = None,
    agent_prompt: str | None = None,
    reasoning_short: str = "mocked",
) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        f"{{"
                        f'"intent":"{intent}",'
                        f'"confidence":{confidence},'
                        f'"simple_reply":{f'"{simple_reply}"' if simple_reply else "null"},'
                        f'"meta_action_id":{f'"{meta_action_id}"' if meta_action_id else "null"},'
                        f'"agent_prompt":{f'"{agent_prompt}"' if agent_prompt else "null"},'
                        f'"reasoning_short":"{reasoning_short}"'
                        f"}}"
                    )
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# _build_router_json_schema
# ---------------------------------------------------------------------------


class TestBuildRouterJsonSchema:
    def test_includes_required_fields(self) -> None:
        schema = _build_router_json_schema()
        assert "intent" in schema["properties"]
        assert "confidence" in schema["properties"]
        assert "simple_reply" in schema["properties"]
        assert "meta_action_id" in schema["properties"]
        assert "agent_prompt" in schema["properties"]
        assert "reasoning_short" in schema["properties"]

    def test_intent_enum_matches_model(self) -> None:
        schema = _build_router_json_schema()
        enum_vals = schema["properties"]["intent"]["enum"]
        expected = sorted(i.value for i in RouterIntent)
        assert sorted(enum_vals) == expected

    def test_strict_mode(self) -> None:
        schema = _build_router_json_schema()
        assert schema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# _catalog_summary
# ---------------------------------------------------------------------------


class TestCatalogSummary:
    def test_empty_catalog(self) -> None:
        result = _catalog_summary(MetaCatalog(agent_binary="agent", actions=[]))
        assert "empty" in result.lower()
        assert "delegate_agent" in result

    def test_none_catalog(self) -> None:
        result = _catalog_summary(None)
        assert "empty" in result.lower()

    def test_single_action(self) -> None:
        catalog = MetaCatalog(
            agent_binary="agent",
            actions=[
                MetaAction(
                    id="session.clear",
                    description="Clear context",
                    labels=["clear", "reset"],
                    delivery="tmux_send_keys",
                ),
            ],
        )
        result = _catalog_summary(catalog)
        assert "session.clear" in result
        assert "Clear context" in result


# ---------------------------------------------------------------------------
# route_transcript — API success path
# ---------------------------------------------------------------------------


class TestRouteTranscriptSuccess:
    @pytest.fixture(autouse=True)
    def _patch_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key-12345")
        load_config.cache_clear()

    def _run(self, mock_decision: dict) -> RouterDecision:
        mock_client = _mock_httpx_client(mock_decision)
        with patch("colab.router.mistral.httpx.Client", return_value=mock_client):
            return route_transcript("bonjour")

    def test_simple_reply(self) -> None:
        decision = self._run(
            _fake_mistral_decision(
                intent="simple_reply",
                simple_reply="Bonjour! Comment puis-je vous aider?",
            )
        )
        assert decision.intent == RouterIntent.SIMPLE_REPLY
        assert decision.simple_reply == "Bonjour! Comment puis-je vous aider?"
        assert decision.confidence > 0.5
        assert decision.reasoning_short == "mocked"

    def test_meta_action(self) -> None:
        decision = self._run(
            _fake_mistral_decision(
                intent="meta_action",
                meta_action_id="session.clear",
            )
        )
        assert decision.intent == RouterIntent.META_ACTION
        assert decision.meta_action_id == "session.clear"

    def test_delegate_agent(self) -> None:
        decision = self._run(
            _fake_mistral_decision(
                intent="delegate_agent",
                agent_prompt="The user said: write a python script",
            )
        )
        assert decision.intent == RouterIntent.DELEGATE_AGENT
        assert decision.agent_prompt is not None

    def test_stop_agent(self) -> None:
        decision = self._run(_fake_mistral_decision(intent="stop_agent"))
        assert decision.intent == RouterIntent.STOP_AGENT

    def test_high_confidence(self) -> None:
        decision = self._run(
            _fake_mistral_decision(
                intent="simple_reply",
                confidence=0.98,
                simple_reply="Oui",
            )
        )
        assert decision.confidence == 0.98


# ---------------------------------------------------------------------------
# route_transcript — API failure path
# ---------------------------------------------------------------------------


class TestRouteTranscriptFailure:
    @pytest.fixture(autouse=True)
    def _patch_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key-12345")
        load_config.cache_clear()

    def _run_with_client(self, mock_client: MagicMock) -> RouterDecision:
        with patch("colab.router.mistral.httpx.Client", return_value=mock_client):
            return route_transcript("bonjour")

    def test_http_error_falls_back(self) -> None:
        mock_client = _mock_httpx_client({}, status=500)
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=MagicMock()
        )
        decision = self._run_with_client(mock_client)
        assert decision.intent == RouterIntent.DELEGATE_AGENT
        assert decision.confidence == 0.0
        assert decision.reasoning_short is not None

    def test_connection_error_falls_back(self) -> None:
        mock_client = _mock_httpx_client({})
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        decision = self._run_with_client(mock_client)
        assert decision.intent == RouterIntent.DELEGATE_AGENT

    def test_timeout_falls_back(self) -> None:
        mock_client = _mock_httpx_client({})
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        decision = self._run_with_client(mock_client)
        assert decision.intent == RouterIntent.DELEGATE_AGENT

    def test_invalid_json_response_falls_back(self) -> None:
        mock_client = _mock_httpx_client({"choices": [{"message": {"content": "{invalid json"}}]})
        decision = self._run_with_client(mock_client)
        assert decision.intent == RouterIntent.DELEGATE_AGENT

    def test_empty_choices_falls_back(self) -> None:
        mock_client = _mock_httpx_client({"choices": []})
        decision = self._run_with_client(mock_client)
        assert decision.intent == RouterIntent.DELEGATE_AGENT


# ---------------------------------------------------------------------------
# route_transcript — no-secret fallback (complement to test_router_stub.py)
# ---------------------------------------------------------------------------


class TestRouteTranscriptNoKey:
    def test_empty_key_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "")
        load_config.cache_clear()
        decision = route_transcript("test")
        assert decision.intent == RouterIntent.DELEGATE_AGENT
        assert decision.confidence == 0.0

    def test_key_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        load_config.cache_clear()
        decision = route_transcript("what is 2+2?")
        assert decision.intent == RouterIntent.DELEGATE_AGENT
        assert decision.agent_prompt is not None
