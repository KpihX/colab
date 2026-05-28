"""Queue integration simulations for orchestrator edge cases."""

from __future__ import annotations

import asyncio
import time

from colab.model import MetaAction, MetaCatalog, MetaDelivery, RouterDecision, RouterIntent
from colab.orchestrator import _drain_delegate_queue, handle_text
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
            )
        ],
    )


def _delegate_decision(prompt: str) -> RouterDecision:
    return RouterDecision(
        intent=RouterIntent.DELEGATE_AGENT,
        confidence=0.9,
        agent_prompt=prompt,
        reasoning_short="delegate",
    )


async def test_handle_text_queues_when_busy(monkeypatch) -> None:
    reset_runtime()
    runtime = get_runtime()
    runtime.try_begin_turn()

    monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
    monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())
    monkeypatch.setattr(
        "colab.orchestrator.route_transcript",
        lambda transcript, catalog: _delegate_decision("live"),
    )

    async def _mock_connected() -> object:
        return object()

    monkeypatch.setattr(runtime, "ensure_connected", _mock_connected)

    speeches = await handle_text("hello")

    assert speeches == []
    assert runtime.queue_depth() == 1
    runtime.end_turn()


async def test_handle_text_delegate_drains_queue_fifo(monkeypatch) -> None:
    reset_runtime()
    runtime = get_runtime()
    runtime.enqueue_delegate("queued-1", "first")
    runtime.enqueue_delegate("queued-2", "second")

    monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
    monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())
    monkeypatch.setattr(
        "colab.orchestrator.route_transcript",
        lambda transcript, catalog: _delegate_decision("live"),
    )

    async def _mock_connected() -> object:
        return object()

    monkeypatch.setattr(runtime, "ensure_connected", _mock_connected)

    async def _mock_run_agent_prompt(session, prompt_text: str) -> str:
        return f"out:{prompt_text}"

    monkeypatch.setattr("colab.orchestrator._run_agent_prompt", _mock_run_agent_prompt)

    speeches = await handle_text("hello")

    assert speeches == ["out:live", "out:queued-1", "out:queued-2"]
    assert runtime.queue_depth() == 0
    assert runtime.busy is False


async def test_drain_requeues_item_when_turn_cannot_start(monkeypatch) -> None:
    reset_runtime()
    runtime = get_runtime()
    runtime.enqueue_delegate("queued-1", "first")
    monkeypatch.setattr(runtime, "try_begin_turn", lambda: None)

    speeches = await _drain_delegate_queue(runtime, session=object())

    assert speeches == []
    assert runtime.queue_depth() == 1


async def test_soak_delegate_fifo_during_long_turn(monkeypatch) -> None:
    """Simulate multiple delegates while a first ACP turn is "busy"."""
    reset_runtime()
    runtime = get_runtime()

    gate = asyncio.Event()

    monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
    monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())
    monkeypatch.setattr(
        "colab.orchestrator.route_transcript",
        lambda transcript, _catalog: RouterDecision(
            intent=RouterIntent.DELEGATE_AGENT,
            confidence=0.9,
            agent_prompt=f"p:{transcript}",
            reasoning_short="delegate",
        ),
    )

    async def _mock_connected() -> object:
        return object()

    monkeypatch.setattr(runtime, "ensure_connected", _mock_connected)

    async def _run_agent_prompt(_session, prompt_text: str) -> str:
        if prompt_text == "p:t1":
            assert await asyncio.wait_for(gate.wait(), timeout=2.0)
        return f"out:{prompt_text}"

    monkeypatch.setattr("colab.orchestrator._run_agent_prompt", _run_agent_prompt)

    t1_task = asyncio.create_task(handle_text("t1"))

    t0 = time.monotonic()
    while not runtime.busy and time.monotonic() - t0 < 2.0:
        await asyncio.sleep(0.01)
    assert runtime.busy is True

    r2 = await handle_text("t2")
    r3 = await handle_text("t3")
    assert r2 == []
    assert r3 == []
    assert runtime.queue_depth() == 2

    gate.set()
    results_t1 = await t1_task

    assert runtime.queue_depth() == 0
    assert results_t1 == ["out:p:t1", "out:p:t2", "out:p:t3"]


async def test_soak_stop_flushes_queue_during_long_turn(monkeypatch) -> None:
    """If STOP comes mid-turn, queue must flush and no queued delegate should run."""
    reset_runtime()
    runtime = get_runtime()

    stop_calls: list[str] = []
    monkeypatch.setattr(
        "colab.runtime.execute_meta_action",
        lambda action_id, _catalog: stop_calls.append(action_id),
    )
    monkeypatch.setattr("colab.audio.tts.stop_speaking", lambda: None)

    session = type("S", (), {})()
    session.connected = True
    session.cancelled = asyncio.Event()

    def _cancel() -> None:
        session.cancelled.set()

    session.cancel = _cancel
    runtime._session = session

    gate = asyncio.Event()

    def _route(transcript: str, _catalog: MetaCatalog) -> RouterDecision:
        if transcript == "t1":
            return RouterDecision(
                intent=RouterIntent.DELEGATE_AGENT,
                confidence=0.9,
                agent_prompt="p:t1",
                reasoning_short="delegate",
            )
        if transcript == "t2":
            return RouterDecision(
                intent=RouterIntent.DELEGATE_AGENT,
                confidence=0.9,
                agent_prompt="p:t2",
                reasoning_short="delegate",
            )
        if transcript == "stop":
            return RouterDecision(
                intent=RouterIntent.STOP_AGENT,
                confidence=0.95,
                reasoning_short="stop",
            )
        raise AssertionError(f"Unexpected transcript: {transcript}")

    monkeypatch.setattr("colab.orchestrator._prepare_visual", lambda: None)
    monkeypatch.setattr("colab.orchestrator.load_catalog", lambda: _catalog())
    monkeypatch.setattr("colab.orchestrator.route_transcript", _route)

    async def _mock_connected() -> object:
        return object()

    monkeypatch.setattr(runtime, "ensure_connected", _mock_connected)

    async def _run_agent_prompt(_session, prompt_text: str) -> str:
        if prompt_text == "p:t1":
            await asyncio.wait_for(gate.wait(), timeout=2.0)
        return f"out:{prompt_text}"

    monkeypatch.setattr("colab.orchestrator._run_agent_prompt", _run_agent_prompt)

    t1_task = asyncio.create_task(handle_text("t1"))

    t0 = time.monotonic()
    while not runtime.busy and time.monotonic() - t0 < 2.0:
        await asyncio.sleep(0.01)
    assert runtime.busy is True

    r2 = await handle_text("t2")
    assert r2 == []
    assert runtime.queue_depth() == 1

    _ = await handle_text("stop")
    assert session.cancelled.is_set() is True
    assert runtime.queue_depth() == 0

    gate.set()
    results_t1 = await t1_task

    assert results_t1 == ["out:p:t1"]
    assert stop_calls.count("session.stop") == 1
