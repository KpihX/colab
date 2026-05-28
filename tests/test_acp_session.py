"""Tests for the async ACP session — uses real AcpClient with mocked subprocess."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from colab.acp.client import AcpClient
from colab.acp.protocol import build_response
from colab.acp.session import AcpSession
from colab.exceptions import AcpError
from colab.model import SessionState


@pytest.fixture
def mock_proc():
    proc = AsyncMock()
    proc.stdin = AsyncMock()
    proc.stdin.write = Mock()  # StreamWriter.write is synchronous
    proc.stdout = AsyncMock()
    proc.returncode = None
    proc.stdout.readline.return_value = b""  # reader exits immediately
    # Synchronous in real asyncio.subprocess.Process
    proc.terminate = Mock()
    proc.kill = Mock()
    return proc


@pytest.fixture
async def session(mock_proc):
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        client = AcpClient("dummy-binary")
        sess = AcpSession(client=client)
        connect_task = asyncio.create_task(sess.connect())
        await asyncio.sleep(0)
        # Feed: initialize (1), authenticate (2), session/new (3)
        await client.feed_line(client.encode_line(build_response(1, {"serverInfo": {"name": "t"}})))
        await asyncio.sleep(0)
        await client.feed_line(client.encode_line(build_response(2, {})))
        await asyncio.sleep(0)
        await client.feed_line(client.encode_line(build_response(3, {"sessionId": "sess_1"})))
        await asyncio.wait_for(connect_task, timeout=1.0)
        yield sess
        await sess.close()


class TestConnect:
    async def test_connect_success(self, mock_proc):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            client = AcpClient("dummy-binary")
            session = AcpSession(client=client)
            task = asyncio.create_task(session.connect())
            await asyncio.sleep(0)
            await client.feed_line(client.encode_line(build_response(1, {"serverInfo": {}})))
            await asyncio.sleep(0)
            await client.feed_line(client.encode_line(build_response(2, {})))
            await asyncio.sleep(0)
            await client.feed_line(client.encode_line(build_response(3, {"sessionId": "sess_X"})))
            state = await asyncio.wait_for(task, timeout=1.0)
            assert isinstance(state, SessionState)
            assert state.session_id == "sess_X"
            assert session.connected
            await session.close()

    async def test_connect_no_session_id(self, mock_proc):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            client = AcpClient("dummy-binary")
            session = AcpSession(client=client)
            task = asyncio.create_task(session.connect())
            await asyncio.sleep(0)

            await client.feed_line(client.encode_line(build_response(1, {"serverInfo": {}})))
            await asyncio.sleep(0)
            await client.feed_line(client.encode_line(build_response(2, {})))
            await asyncio.sleep(0)
            await client.feed_line(client.encode_line(build_response(3, {})))

            with pytest.raises(AcpError, match="sessionId"):
                await asyncio.wait_for(task, timeout=1.0)
            await session.close()


class TestPrompt:
    async def test_yields_text_chunks(self, session, mock_proc):
        client = session._client
        chunks = []

        async def collect():
            async for c in session.prompt("hello", voice_wrap=False):
                chunks.append(c)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)

        # Feed session/update notifications
        def update_notification(text: str) -> dict:
            return {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"text": text},
                    }
                },
            }

        await client.feed_line(client.encode_line(update_notification("Hi ")))
        await asyncio.sleep(0)
        await client.feed_line(client.encode_line(update_notification("there")))
        await asyncio.sleep(0)

        # Resolve the session/prompt request (ID=4)
        await client.feed_line(client.encode_line(build_response(4, {"stopReason": "finished"})))

        await asyncio.wait_for(task, timeout=2.0)
        texts = [c.text for c in chunks if c.text]
        assert texts == ["Hi ", "there"]

    async def test_final_chunk(self, session, mock_proc):
        client = session._client
        chunks = []

        async def collect():
            async for c in session.prompt("hello", voice_wrap=False):
                chunks.append(c)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await asyncio.sleep(0)  # let request_task create future id=4

        # Resolve immediately with stopReason
        await client.feed_line(client.encode_line(build_response(4, {"stopReason": "finished"})))

        await asyncio.wait_for(task, timeout=2.0)
        final = [c for c in chunks if c.is_final]
        assert len(final) == 1
        assert final[0].text == ""

    async def test_not_connected_error(self, mock_proc):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            session = AcpSession(client=AcpClient("dummy-binary"))
            gen = session.prompt("text")
            with pytest.raises(AcpError, match="Not connected"):
                await gen.__anext__()
            await session.close()


class TestCancel:
    async def test_cancel_is_lazy_marker(self, session, mock_proc):
        session.cancel()
        # Cancel is a thread-safe marker — doesn't call notify until prompt loop runs
        assert session._cancelled

    async def test_cancel_triggers_in_prompt(self, session, mock_proc):
        chunks = []

        async def collect():
            async for c in session.prompt("hello", voice_wrap=False):
                chunks.append(c)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)

        # Cancel before the request resolves
        session.cancel()

        await asyncio.wait_for(task, timeout=2.0)
        # Should have yielded final chunk
        final_chunks = [c for c in chunks if c.is_final]
        assert len(final_chunks) >= 1


class TestClose:
    async def test_close_stops_client(self, session, mock_proc):
        assert session.connected
        await session.close()
        assert not session.connected
        assert session.session_id is None

    async def test_close_idempotent(self, session, mock_proc):
        await session.close()
        await session.close()
