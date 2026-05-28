"""FIFO prompt queue for delegate_agent while the ACP session is busy."""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class QueuedPrompt:
    """One deferred agent delegation."""

    turn_id: str
    prompt_text: str
    source_transcript: str
    enqueued_at: float


class PromptQueue:
    """Thread-safe FIFO queue with monotonic turn ids."""

    _counter = itertools.count(1)

    def __init__(self, *, max_size: int = 10) -> None:
        self._max_size = max(1, max_size)
        self._items: deque[QueuedPrompt] = deque()
        self._lock = threading.Lock()

    @classmethod
    def new_turn_id(cls) -> str:
        return f"turn-{next(cls._counter)}"

    def enqueue(self, prompt_text: str, source_transcript: str) -> str | None:
        """Append prompt. Returns turn_id or None if queue is full."""
        with self._lock:
            if len(self._items) >= self._max_size:
                return None
            turn_id = self.new_turn_id()
            self._items.append(
                QueuedPrompt(
                    turn_id=turn_id,
                    prompt_text=prompt_text,
                    source_transcript=source_transcript,
                    enqueued_at=time.monotonic(),
                )
            )
            return turn_id

    def pop(self) -> QueuedPrompt | None:
        with self._lock:
            if not self._items:
                return None
            return self._items.popleft()

    def push_left(self, item: QueuedPrompt) -> None:
        with self._lock:
            self._items.appendleft(item)

    def flush(self) -> list[QueuedPrompt]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items

    def depth(self) -> int:
        with self._lock:
            return len(self._items)

    def snapshot(self) -> list[QueuedPrompt]:
        with self._lock:
            return list(self._items)
