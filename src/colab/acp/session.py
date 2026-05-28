"""High-level ACP session API — async."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

from colab.acp.client import AcpClient
from colab.acp.protocol import PROTOCOL_VERSION, parse_session_update
from colab.config import get_agent_binary, load_config
from colab.exceptions import AcpError
from colab.model import AgentChunk, SessionState

logger = logging.getLogger(__name__)


def wrap_voice_prompt(transcript: str) -> str:
    cfg = load_config()
    template = cfg.get("router", {}).get("voice_prompt_wrapper", "{transcript}")
    if "{transcript}" in template:
        return template.format(transcript=transcript)
    return f"{template}\n{transcript}"


class AcpSession:
    """Manage one persistent ACP session — async."""

    def __init__(self, client: AcpClient | None = None, cwd: str | None = None) -> None:
        cfg = load_config()["agents"]["default"]
        permission = cfg.get("permission_policy", "allow-once")
        self._client = client or AcpClient(
            get_agent_binary(),
            extra_args=cfg.get("acp_args", ["acp"]),
            permission_policy=permission,
        )
        self._cwd = cwd or str(Path(cfg.get("cwd", "~")).expanduser())
        self._session_id: str | None = None
        self._mode = cfg.get("mode", "agent")
        self._agent_name = cfg.get("name", "default")
        self._connected = False
        self._cancelled = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def connected(self) -> bool:
        return self._connected and self._session_id is not None

    async def connect(self) -> SessionState:
        """initialize + authenticate + session/new (async)."""
        if not self._client.is_running:
            await self._client.start()

        init_result = await self._client.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "colab", "version": "0.1.0"},
            },
        )
        logger.debug("ACP initialize: %s", list(init_result.keys()))

        await self._client.request("authenticate", {"methodId": "cursor_login"})

        session_result = await self._client.request(
            "session/new",
            {"cwd": self._cwd, "mcpServers": []},
        )
        session_id = session_result.get("sessionId")
        if not session_id:
            raise AcpError("session/new did not return sessionId")

        self._session_id = str(session_id)
        self._connected = True
        return SessionState(
            session_id=self._session_id,
            cwd=self._cwd,
            agent_name=self._agent_name,
            mode=self._mode,
        )

    async def prompt(
        self,
        text: str,
        *,
        voice_wrap: bool = True,
        initial_timeout_s: float | None = 10.0,
        idle_timeout_s: float | None = 5.0,
        max_turn_time_s: float | None = 120.0,
    ) -> AsyncIterator[AgentChunk]:
        """session/prompt + stream session/update until done — async generator."""
        if not self.connected:
            raise AcpError("Not connected — call connect() first")

        prompt_text = wrap_voice_prompt(text) if voice_wrap else text
        params: dict[str, object] = {
            "sessionId": self._session_id,
            "prompt": [{"type": "text", "text": prompt_text}],
        }

        request_task = asyncio.create_task(self._client.request("session/prompt", params))

        turn_start = time.monotonic()
        last_activity = turn_start
        saw_any_chunk = False
        cancelled_by_guard = False
        yielded_final = False

        try:
            while not request_task.done() or self._client.has_pending_notifications():
                if self._cancelled:
                    self._cancelled = False
                    cancelled_by_guard = True
                    yield AgentChunk(text="", is_final=True)
                    break

                try:
                    msg = await asyncio.wait_for(self._client._notifications.get(), timeout=0.1)
                except TimeoutError:
                    now = time.monotonic()
                    if (
                        initial_timeout_s is not None
                        and not saw_any_chunk
                        and now - turn_start > initial_timeout_s
                        and not request_task.done()
                    ):
                        logger.warning(
                            "ACP turn no chunks after %.1fs; cancelling",
                            initial_timeout_s,
                        )
                        await self._cancel()
                        cancelled_by_guard = True
                        break

                    if max_turn_time_s is not None and now - turn_start > max_turn_time_s:
                        logger.warning(
                            "ACP turn exceeded max_turn_time_s=%.1f; cancelling",
                            max_turn_time_s,
                        )
                        await self._cancel()
                        cancelled_by_guard = True
                        break

                    if (
                        idle_timeout_s is not None
                        and saw_any_chunk
                        and now - last_activity > idle_timeout_s
                    ):
                        if not request_task.done():
                            logger.warning(
                                "ACP turn idle for %.1fs; cancelling",
                                idle_timeout_s,
                            )
                            await self._cancel()
                            cancelled_by_guard = True
                        break

                    if request_task.done() and not self._client.has_pending_notifications():
                        break
                    continue

                if msg.get("method") != "session/update":
                    continue

                raw_params = msg.get("params")
                if not isinstance(raw_params, dict):
                    continue

                chunk = parse_session_update(raw_params)
                if chunk is not None:
                    saw_any_chunk = True
                    last_activity = time.monotonic()
                    yield chunk
        finally:
            if not request_task.done():
                request_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await request_task
            if not cancelled_by_guard and not yielded_final:
                yield AgentChunk(text="", is_final=True)
                yielded_final = True

    async def _cancel(self) -> None:
        if not self._session_id:
            return
        if self._client.is_running:
            await self._client.notify("session/cancel", {"sessionId": self._session_id})

    def cancel(self) -> None:
        """Signal cancel — thread-safe marker for the prompt loop."""
        self._cancelled = True

    async def close(self) -> None:
        self._connected = False
        self._session_id = None
        await self._client.stop()
