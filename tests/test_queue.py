"""Tests for PromptQueue."""

from __future__ import annotations

from colab.queue import PromptQueue


def test_enqueue_pop_fifo() -> None:
    q = PromptQueue(max_size=3)
    t1 = q.enqueue("first", "transcript one")
    t2 = q.enqueue("second", "transcript two")
    assert t1 is not None and t2 is not None
    assert t1 != t2

    first = q.pop()
    assert first is not None
    assert first.turn_id == t1
    assert first.prompt_text == "first"

    second = q.pop()
    assert second is not None
    assert second.turn_id == t2

    assert q.pop() is None


def test_flush_clears_queue() -> None:
    q = PromptQueue(max_size=5)
    q.enqueue("a", "x")
    q.enqueue("b", "y")
    flushed = q.flush()
    assert len(flushed) == 2
    assert q.depth() == 0
    assert q.pop() is None


def test_max_size_rejects() -> None:
    q = PromptQueue(max_size=2)
    assert q.enqueue("one", "t") is not None
    assert q.enqueue("two", "t") is not None
    assert q.enqueue("three", "t") is None
    assert q.depth() == 2
