"""Tests for AgentRuntime."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from colab.model import MetaAction, MetaCatalog, MetaDelivery
from colab.runtime import AgentRuntime, reset_runtime


def test_stop_agent_cancels_and_sends_tmux() -> None:
    reset_runtime()
    runtime = AgentRuntime()
    session = MagicMock()
    session.connected = True
    runtime._session = session  # noqa: SLF001

    catalog = MetaCatalog(
        agent_binary="agent",
        agent_version_hash="abc",
        discovered_at="2026-01-01T00:00:00+00:00",
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

    runtime.enqueue_delegate("queued prompt", "transcript")
    assert runtime.queue_depth() == 1

    with patch("colab.runtime.execute_meta_action") as execute:
        runtime.stop_agent(catalog)
        session.cancel.assert_called_once()
        execute.assert_called_once_with("session.stop", catalog)
        assert runtime.busy is False
        assert runtime.queue_depth() == 0
