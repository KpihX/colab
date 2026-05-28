"""Tests for the async ACP client."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from colab.acp.client import AcpClient
from colab.acp.protocol import build_request, build_response
from colab.exceptions import AcpError


@pytest.fixture
def mock_proc():
    """Return a mock asyncio.subprocess.Process with fake stdin/stdout."""
    proc = AsyncMock()
    proc.stdin = AsyncMock()
    proc.stdin.write = Mock()  # StreamWriter.write is synchronous
    proc.stdout = AsyncMock()
    proc.returncode = None
    proc.stdout.readline.return_value = b""  # exit reader loop immediately
    # Synchronous in real asyncio.subprocess.Process
    proc.terminate = Mock()
    proc.kill = Mock()
    return proc


@pytest.fixture
async def client(mock_proc):
    """AcpClient with mocked subprocess, started."""
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        c = AcpClient("dummy-binary")
        await c.start()
        yield c
        await c.stop()


class TestStartStop:
    async def test_start(self, mock_proc):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary")
            assert not c.is_running
            await c.start()
            assert c.is_running
            await c.stop()
            assert not c.is_running

    async def test_start_twice(self, mock_proc):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary")
            await c.start()
            await c.start()  # no-op
            assert c.is_running
            await c.stop()

    async def test_stop_cleanup_pending(self, mock_proc):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary", request_timeout_s=300)
            await c.start()
            asyncio.create_task(c.request("test/method"))
            await asyncio.sleep(0)
            await c.stop()
            assert not c.is_running

    async def test_stop_kill_on_timeout(self, mock_proc):
        mock_proc.wait.side_effect = asyncio.TimeoutError
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary")
            await c.start()
            await c.stop()
            mock_proc.kill.assert_called_once()


class TestRequestResponse:
    async def test_basic_request_response(self, client, mock_proc):
        task = asyncio.create_task(client.request("test/method"))
        await asyncio.sleep(0)
        await client.feed_line(AcpClient.encode_line(build_response(1, {"ok": True})))
        result = await task
        assert result == {"ok": True}

    async def test_request_with_params(self, client, mock_proc):
        task = asyncio.create_task(client.request("test/echo", {"msg": "hello"}))
        await asyncio.sleep(0)
        await client.feed_line(AcpClient.encode_line(build_response(1, {"echo": "hello"})))
        result = await task
        assert result == {"echo": "hello"}

    async def test_request_error(self, client, mock_proc):
        task = asyncio.create_task(client.request("test/fail"))
        await asyncio.sleep(0)
        err_response = {"id": 1, "error": {"code": -1, "message": "fail"}}
        await client.feed_line(AcpClient.encode_line(err_response))
        with pytest.raises(AcpError, match="fail"):
            await task

    async def test_notify_not_started(self):
        c = AcpClient("dummy-binary")
        with pytest.raises(AcpError, match="not started"):
            await c.notify("test/method")

    async def test_request_not_started(self):
        c = AcpClient("dummy-binary")
        with pytest.raises(AcpError, match="not started"):
            await c.request("test/method")


class TestReaderLoop:
    async def test_reader_delivers_response(self, mock_proc):
        mock_proc.stdout.readline.side_effect = [
            AcpClient.encode_line(build_response(1, {"ok": True})),
            b"",
        ]
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary")
            await c.start()
            result = await c.request("test/method")
            assert result == {"ok": True}
            mock_proc.stdin.write.assert_called()  # request sent
            await c.stop()

    async def test_reader_loop_terminate(self, mock_proc):
        mock_proc.stdout.readline.return_value = b""
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary")
            await c.start()
            await asyncio.sleep(0.01)
            await c.stop()

    async def test_reader_loop_invalid_json(self, mock_proc):
        mock_proc.stdout.readline.side_effect = [
            b"not json\n",
            b"",
        ]
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary")
            await c.start()
            await asyncio.sleep(0.01)
            await c.stop()


class TestServerRequests:
    async def test_permission_allow_once(self, client, mock_proc):
        params = {
            "options": [{"optionId": "allow-once", "label": "Allow once"}],
        }
        await client.feed_line(
            AcpClient.encode_line(build_request(99, "session/request_permission", params))
        )
        await asyncio.sleep(0)
        written = mock_proc.stdin.write.call_args[0][0]
        decoded = json.loads(written.decode())
        assert decoded.get("id") == 99
        assert decoded.get("result", {}).get("outcome", {}).get("optionId") == "allow-once"

    async def test_permission_no_match(self, mock_proc):
        params = {
            "options": [{"optionId": "always", "label": "Always"}],
        }
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            c = AcpClient("dummy-binary", permission_policy="allow-once")
            await c.start()
            await c.feed_line(
                AcpClient.encode_line(build_request(99, "session/request_permission", params))
            )
            await asyncio.sleep(0)
            written = mock_proc.stdin.write.call_args[0][0]
            decoded = json.loads(written.decode())
            assert decoded.get("result", {}).get("outcome", {}).get("optionId") == "always"
            await c.stop()

    async def test_cursor_ask_question(self, client, mock_proc):
        params = {
            "questions": [
                {
                    "id": "q1",
                    "options": [{"id": "opt_a", "label": "Option A"}],
                }
            ],
        }
        await client.feed_line(
            AcpClient.encode_line(build_request(99, "cursor/ask_question", params))
        )
        await asyncio.sleep(0)
        written = mock_proc.stdin.write.call_args[0][0]
        decoded = json.loads(written.decode())
        result = decoded.get("result", {})
        outcome = result.get("outcome", {})
        assert outcome.get("outcome") == "answered"
        answers = outcome.get("answers", [])
        assert len(answers) == 1
        assert answers[0]["questionId"] == "q1"
        assert answers[0]["selectedOptionIds"] == ["opt_a"]

    async def test_cursor_create_plan(self, client, mock_proc):
        await client.feed_line(AcpClient.encode_line(build_request(99, "cursor/create_plan")))
        await asyncio.sleep(0)
        written = mock_proc.stdin.write.call_args[0][0]
        decoded = json.loads(written.decode())
        result = decoded.get("result", {})
        assert result.get("outcome", {}).get("outcome") == "accepted"


class TestNotifications:
    async def test_iter_notifications(self, client, mock_proc):
        # Inject two session/update notifications, then stop
        notif = {"method": "session/update", "params": {"text": "hello"}}
        await client.feed_line(AcpClient.encode_line(notif))
        notif2 = {"method": "session/update", "params": {"text": "world"}}
        await client.feed_line(AcpClient.encode_line(notif2))

        seen = []
        async for msg in client.iter_notifications(timeout=0.05):
            seen.append(msg)
        assert len(seen) == 2
        assert seen[0]["params"]["text"] == "hello"
        assert seen[1]["params"]["text"] == "world"

    async def test_drain_notifications(self, client, mock_proc):
        notif = {"method": "session/update", "params": {}}
        await client.feed_line(AcpClient.encode_line(notif))
        await client.feed_line(AcpClient.encode_line(notif))
        drained = client.drain_notifications()
        assert len(drained) == 2

    async def test_has_pending_notifications(self, client, mock_proc):
        assert not client.has_pending_notifications()
        await client.feed_line(AcpClient.encode_line({"method": "session/update", "params": {}}))
        assert client.has_pending_notifications()


class TestEdgeCases:
    async def test_feed_line_invalid_json(self, client, mock_proc):
        await client.feed_line(b"not json\n")
        # Should not crash

    async def test_response_unknown_id(self, client, mock_proc):
        await client.feed_line(AcpClient.encode_line({"id": 999, "result": {}}))
        # Should not crash
