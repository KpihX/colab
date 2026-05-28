"""Full voice E2E soak tests — mocked audio, real dispatch.

Exercises:
- handle_text for all 4 intents (SIMPLE_REPLY, META_ACTION, DELEGATE_AGENT, STOP_AGENT)
- _speak_with_barge_in with mocked player
- Multi-iteration soak (N rounds of SIMPLE_REPLY)
- All intents in sequence with state verification
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from colab.model import MetaAction, MetaCatalog, MetaDelivery, RouterDecision, RouterIntent
from colab.orchestrator import _speak_with_barge_in, handle_text
from colab.runtime import get_runtime, reset_runtime


def _catalog() -> MetaCatalog:
    return MetaCatalog(
        agent_binary="agent",
        agent_version_hash="abc",
        actions=[
            MetaAction(
                id="session.stop",
                description="stop",
                labels=["stop"],
                delivery=MetaDelivery.TMUX_SEND_KEYS,
                payload={"keys": "C-c", "enter": False},
            ),
            MetaAction(
                id="session.clear",
                description="Clear conversation / new topic",
                labels=["clear"],
                delivery=MetaDelivery.TMUX_SEND_KEYS,
                payload={"keys": "/clear", "enter": True},
            ),
        ],
    )


# ---------------------------------------------------------------------------
# handle_text — SIMPLE_REPLY
# ---------------------------------------------------------------------------


class TestHandleTextSimpleReply:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_runtime()
        monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
        monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())

    def test_returns_simple_reply_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "colab.orchestrator.route_transcript",
            lambda _t, _c: RouterDecision(
                intent=RouterIntent.SIMPLE_REPLY,
                confidence=0.95,
                simple_reply="Bonjour!",
                reasoning_short="greeting",
            ),
        )
        speeches = asyncio.run(handle_text("bonjour"))
        assert speeches == ["Bonjour!"]

    def test_empty_simple_reply_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "colab.orchestrator.route_transcript",
            lambda _t, _c: RouterDecision(
                intent=RouterIntent.SIMPLE_REPLY,
                confidence=0.5,
                simple_reply=None,
                reasoning_short="unsure",
            ),
        )
        speeches = asyncio.run(handle_text("hmm"))
        assert speeches == []

    async def test_soak_simple_reply_n_times(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """N iterations of SIMPLE_REPLY to verify loop stability."""
        n = 10
        monkeypatch.setattr(
            "colab.orchestrator.route_transcript",
            lambda _t, _c: RouterDecision(
                intent=RouterIntent.SIMPLE_REPLY,
                confidence=0.9,
                simple_reply="hello",
                reasoning_short="greeting",
            ),
        )
        for i in range(n):
            speeches = await handle_text(f"hello-{i}")
            assert speeches == ["hello"]


# ---------------------------------------------------------------------------
# handle_text — META_ACTION
# ---------------------------------------------------------------------------


class TestHandleTextMetaAction:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_runtime()
        monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
        monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())

    def test_executes_meta_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "colab.orchestrator.route_transcript",
            lambda _t, _c: RouterDecision(
                intent=RouterIntent.META_ACTION,
                confidence=0.9,
                meta_action_id="session.clear",
                reasoning_short="user wants new topic",
            ),
        )
        calls: list[str] = []
        monkeypatch.setattr(
            "colab.orchestrator.execute_meta_action",
            lambda action_id, _c: calls.append(action_id),
        )
        speeches = asyncio.run(handle_text("changeons de sujet"))
        assert speeches == []
        assert calls == ["session.clear"]


# ---------------------------------------------------------------------------
# handle_text — STOP_AGENT
# ---------------------------------------------------------------------------


class TestHandleTextStopAgent:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_runtime()
        monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
        monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())
        monkeypatch.setattr("colab.audio.tts.stop_speaking", lambda: None)

    async def test_stops_agent_and_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "colab.orchestrator.route_transcript",
            lambda _t, _c: RouterDecision(
                intent=RouterIntent.STOP_AGENT,
                confidence=0.95,
                reasoning_short="user wants to stop",
            ),
        )
        runtime = get_runtime()
        stop_calls: list[str] = []
        monkeypatch.setattr(
            runtime,
            "stop_agent",
            lambda catalog: stop_calls.append("stop"),
        )
        speeches = await handle_text("stop")
        assert speeches == []
        assert stop_calls == ["stop"]


# ---------------------------------------------------------------------------
# handle_text — DELEGATE_AGENT (complement to test_orchestrator_queue)
# ---------------------------------------------------------------------------


class TestHandleTextDelegate:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_runtime()
        monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
        monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())

    async def test_delegates_when_idle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime = get_runtime()
        monkeypatch.setattr(
            "colab.orchestrator.route_transcript",
            lambda _t, _c: RouterDecision(
                intent=RouterIntent.DELEGATE_AGENT,
                confidence=0.9,
                agent_prompt="write tests",
                reasoning_short="coding request",
            ),
        )

        async def _mock_connected() -> object:
            return object()

        monkeypatch.setattr(runtime, "ensure_connected", _mock_connected)

        async def _mock_run(session, prompt_text: str) -> str:
            return f"out:{prompt_text}"

        monkeypatch.setattr("colab.orchestrator._run_agent_prompt", _mock_run)

        speeches = await handle_text("write tests")
        assert speeches == ["out:write tests"]
        assert runtime.busy is False


# ---------------------------------------------------------------------------
# _speak_with_barge_in
# ---------------------------------------------------------------------------


class TestSpeakWithBargeIn:
    @pytest.fixture
    def mock_player(self) -> MagicMock:
        player = MagicMock()
        player.is_speaking = False
        player.stop_requested = False
        return player

    async def test_speak_completes_without_interrupt(self, monkeypatch, mock_player) -> None:
        monkeypatch.setattr("colab.audio.tts.get_tts_player", lambda: mock_player)

        def speak(text: str) -> None:
            mock_player.is_speaking = True
            mock_player.stop_requested = False

        mock_player.speak = speak

        with patch(
            "colab.audio.barge_in.wait_for_barge_in",
            return_value=False,
        ):
            interrupted = await _speak_with_barge_in("hello")
        assert interrupted is False

    async def test_barge_in_interrupts(self, monkeypatch, mock_player) -> None:
        monkeypatch.setattr("colab.audio.tts.get_tts_player", lambda: mock_player)

        mock_player.stop_requested = True

        with patch(
            "colab.audio.barge_in.wait_for_barge_in",
            return_value=True,
        ):
            interrupted = await _speak_with_barge_in("hello")
        assert interrupted is True
        mock_player.stop_speaking.assert_called_once()


# ---------------------------------------------------------------------------
# Soak: all intents in sequence
# ---------------------------------------------------------------------------


class TestSoakAllIntents:
    """Sequences through all 4 intents to verify state machine stability."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_runtime()
        monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
        monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())
        monkeypatch.setattr("colab.audio.tts.stop_speaking", lambda: None)

    async def test_sequence_simple_meta_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime = get_runtime()
        transcripts: list[str] = []
        decisions = iter(
            [
                RouterDecision(
                    intent=RouterIntent.SIMPLE_REPLY,
                    confidence=0.95,
                    simple_reply="salut",
                    reasoning_short="greeting",
                ),
                RouterDecision(
                    intent=RouterIntent.META_ACTION,
                    confidence=0.9,
                    meta_action_id="session.clear",
                    reasoning_short="new topic",
                ),
                RouterDecision(
                    intent=RouterIntent.STOP_AGENT,
                    confidence=0.98,
                    reasoning_short="user stop",
                ),
            ]
        )

        def _route(transcript: str, _catalog: MetaCatalog) -> RouterDecision:
            transcripts.append(transcript)
            return next(decisions)

        monkeypatch.setattr("colab.orchestrator.route_transcript", _route)
        meta_calls: list[str] = []
        monkeypatch.setattr(
            "colab.orchestrator.execute_meta_action",
            lambda action_id, _c: meta_calls.append(action_id),
        )
        stop_calls: list[str] = []
        monkeypatch.setattr(runtime, "stop_agent", lambda catalog: stop_calls.append("stop"))

        s1 = await handle_text("salut")
        assert s1 == ["salut"]

        s2 = await handle_text("changeons")
        assert s2 == []
        assert meta_calls == ["session.clear"]

        s3 = await handle_text("stop")
        assert s3 == []
        assert stop_calls == ["stop"]

    async def test_soak_simple_then_delegate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interleave simple_replies with one delegate to verify no cross-contamination."""
        runtime = get_runtime()
        transcripts: list[str] = []
        decisions = iter(
            [
                RouterDecision(
                    intent=RouterIntent.SIMPLE_REPLY,
                    confidence=0.9,
                    simple_reply="hello",
                    reasoning_short="greeting",
                ),
                RouterDecision(
                    intent=RouterIntent.SIMPLE_REPLY,
                    confidence=0.9,
                    simple_reply="hi again",
                    reasoning_short="greeting",
                ),
                RouterDecision(
                    intent=RouterIntent.DELEGATE_AGENT,
                    confidence=0.9,
                    agent_prompt="do something",
                    reasoning_short="coding",
                ),
            ]
        )

        def _route(transcript: str, _catalog: MetaCatalog) -> RouterDecision:
            transcripts.append(transcript)
            return next(decisions)

        monkeypatch.setattr("colab.orchestrator.route_transcript", _route)

        async def _mock_connected() -> object:
            return object()

        monkeypatch.setattr(runtime, "ensure_connected", _mock_connected)

        async def _mock_run(session, prompt_text: str) -> str:
            return f"processed:{prompt_text}"

        monkeypatch.setattr("colab.orchestrator._run_agent_prompt", _mock_run)

        s1 = await handle_text("a")
        assert s1 == ["hello"]
        assert runtime.busy is False

        s2 = await handle_text("b")
        assert s2 == ["hi again"]

        s3 = await handle_text("c")
        assert s3 == ["processed:do something"]
        assert runtime.busy is False
