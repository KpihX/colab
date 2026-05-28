"""Persistent agent runtime: ACP session, busy state, prompt queue."""

from __future__ import annotations

import logging
import threading
from typing import Any

from colab.acp.meta import execute_meta_action
from colab.acp.session import AcpSession
from colab.model import MetaCatalog
from colab.queue import PromptQueue, QueuedPrompt

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Owns one ACP session, busy flag, and optional delegate prompt queue."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        from colab.config import load_config

        cfg = config or load_config()
        queue_cfg = cfg.get("queue", {})
        self._queue_enabled = bool(queue_cfg.get("enabled", True))
        max_size = int(queue_cfg.get("max_size", 10))
        self._queue = PromptQueue(max_size=max_size)

        self._session: AcpSession | None = None
        self._busy = False
        self._active_turn_id: str | None = None
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def active_turn_id(self) -> str | None:
        with self._lock:
            return self._active_turn_id

    def is_queue_enabled(self) -> bool:
        return self._queue_enabled

    def queue_depth(self) -> int:
        return self._queue.depth()

    def queue_snapshot(self) -> list[QueuedPrompt]:
        return self._queue.snapshot()

    def try_begin_turn(self) -> str | None:
        with self._lock:
            if self._busy:
                return None
            self._busy = True
            self._active_turn_id = PromptQueue.new_turn_id()
            return self._active_turn_id

    def end_turn(self) -> None:
        with self._lock:
            self._busy = False
            self._active_turn_id = None

    def enqueue_delegate(self, prompt_text: str, source_transcript: str) -> str | None:
        return self._queue.enqueue(prompt_text, source_transcript)

    def pop_queued(self) -> QueuedPrompt | None:
        return self._queue.pop()

    def requeue_front(self, item: QueuedPrompt) -> None:
        self._queue.push_left(item)

    def flush_queue(self) -> list[QueuedPrompt]:
        return self._queue.flush()

    async def ensure_connected(self) -> AcpSession:
        if self._session is None or not self._session.connected:
            from colab.acp.client import AcpClient

            binary = self._get_agent_binary()
            client = AcpClient(binary)
            self._session = AcpSession(client)
            await self._session.connect()
        return self._session

    @staticmethod
    def _get_agent_binary() -> str:
        from colab.config import get_agent_binary

        return get_agent_binary()

    def stop_agent(self, catalog: MetaCatalog) -> None:
        flushed = self.flush_queue()
        if flushed:
            logger.info("Flushed %d queued prompt(s) on stop", len(flushed))

        session = self._session
        if session is not None and session.connected:
            try:
                session.cancel()
            except Exception as exc:
                logger.warning("session/cancel failed: %s", exc)

        with self._lock:
            self._busy = False
            self._active_turn_id = None

        action = next((a for a in catalog.actions if a.id == "session.stop"), None)
        if action is not None:
            execute_meta_action("session.stop", catalog)

    def cleanup(self) -> None:
        """Best-effort sync cleanup for signal handlers."""
        if self._session is not None:
            try:
                self._session.cancel()
            except Exception:
                pass
        self._session = None
        with self._lock:
            self._busy = False
            self._active_turn_id = None

    async def close(self) -> None:
        """Proper async cleanup."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None
        with self._lock:
            self._busy = False
            self._active_turn_id = None


_runtime: AgentRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> AgentRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = AgentRuntime()
        return _runtime


def reset_runtime() -> None:
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            _runtime.cleanup()
        _runtime = None
