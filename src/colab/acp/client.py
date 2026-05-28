"""ACP JSON-RPC client over stdio (newline-delimited JSON) — async."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from colab.acp.protocol import (
    build_notification,
    build_request,
    build_response,
    decode_line,
    permission_response,
)
from colab.exceptions import AcpError

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT_S = 300.0


class AcpClient:
    """Spawn `agent acp` (or inject pipes) and exchange NDJSON messages — fully async."""

    def __init__(
        self,
        binary: str,
        extra_args: list[str] | None = None,
        *,
        permission_policy: str = "allow-once",
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
        stdin: asyncio.StreamWriter | None = None,
        stdout: asyncio.StreamReader | None = None,
    ) -> None:
        self.binary = binary
        self.extra_args = extra_args or ["acp"]
        self.permission_policy = permission_policy
        self.request_timeout_s = request_timeout_s
        self._external_stdin = stdin
        self._external_stdout = stdout
        self._proc: asyncio.subprocess.Process | None = None
        self._stdin: asyncio.StreamWriter | None = None
        self._stdout: asyncio.StreamReader | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._injected_io = False
        self._stopped = False

    @property
    def is_running(self) -> bool:
        if self._proc is not None:
            return self._proc.returncode is None
        return self._stdin is not None and self._stdout is not None and not self._stopped

    async def start(self) -> None:
        if self.is_running:
            return

        if self._external_stdin is not None and self._external_stdout is not None:
            self._stdin = self._external_stdin
            self._stdout = self._external_stdout
            self._injected_io = True
        else:
            cmd = [self.binary, *self.extra_args]
            logger.info("Starting ACP subprocess: %s", " ".join(cmd))
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._stdin = self._proc.stdin
            self._stdout = self._proc.stdout

        self._stop_event.clear()
        self._stopped = False
        self._reader_task = asyncio.create_task(self._reader_loop(), name="acp-reader")

    async def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await asyncio.wait_for(self._reader_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            self._reader_task = None

        if self._proc is not None:
            if self._proc.returncode is None:
                try:
                    self._proc.terminate()
                    await asyncio.wait_for(self._proc.wait(), timeout=5.0)
                except (TimeoutError, ProcessLookupError):
                    try:
                        self._proc.kill()
                        await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                    except (TimeoutError, ProcessLookupError):
                        pass
            self._proc = None

        self._stdin = None
        self._stdout = None

        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_running:
            raise AcpError("ACP client not started — call start() first")

        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[req_id] = future

        payload = build_request(req_id, method, params)
        try:
            await self._write(payload)
            msg = await asyncio.wait_for(future, timeout=self.request_timeout_s)
        except TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise AcpError(f"ACP request timed out: {method}") from exc
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            raise
        finally:
            self._pending.pop(req_id, None)

        if "error" in msg:
            err = msg["error"]
            code = err.get("code", "?")
            message = err.get("message", "unknown error")
            raise AcpError(f"ACP {method} failed ({code}): {message}")

        result = msg.get("result")
        if not isinstance(result, dict):
            return {}
        return result

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.is_running:
            raise AcpError("ACP client not started — call start() first")
        await self._write(build_notification(method, params))

    async def iter_notifications(self, *, timeout: float = 0.05) -> AsyncIterator[dict[str, Any]]:
        while self.is_running and not self._stop_event.is_set():
            try:
                msg = await asyncio.wait_for(self._notifications.get(), timeout=timeout)
                yield msg
            except TimeoutError:
                break

    def drain_notifications(self) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        while not self._notifications.empty():
            try:
                drained.append(self._notifications.get_nowait())
            except asyncio.QueueEmpty:
                break
        return drained

    def has_pending_notifications(self) -> bool:
        return not self._notifications.empty()

    async def feed_line(self, line: str | bytes) -> None:
        """Inject one NDJSON line (tests)."""
        try:
            msg = decode_line(line)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid ACP line: %s", exc)
            return
        self._dispatch(msg)

    @staticmethod
    def encode_line(payload: dict[str, Any]) -> bytes:
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    async def _write(self, payload: dict[str, Any]) -> None:
        if self._stdin is None:
            raise AcpError("ACP stdin not available")
        line = self.encode_line(payload)
        async with self._write_lock:
            self._stdin.write(line)
            await self._stdin.drain()

    async def _reader_loop(self) -> None:
        if self._stdout is None:
            return
        try:
            while not self._stop_event.is_set():
                raw = await self._stdout.readline()
                if not raw:
                    if self._proc is not None and self._proc.returncode is not None:
                        logger.debug("ACP subprocess stdout closed")
                        break
                    if self._injected_io:
                        await asyncio.sleep(0.01)
                        continue
                    logger.debug("ACP stdout closed")
                    break
                try:
                    msg = decode_line(raw)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    logger.warning("Skipping invalid ACP line: %s", exc)
                    continue
                self._dispatch(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("ACP reader loop crashed")

    def _dispatch(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        msg_id = msg.get("id")

        if method is not None and msg_id is not None:
            asyncio.create_task(self._handle_server_request(msg))
            return

        if method is not None:
            self._notifications.put_nowait(msg)
            return

        if msg_id is not None:
            future = self._pending.get(int(msg_id))
            if future is not None and not future.done():
                future.set_result(msg)
            else:
                logger.debug("ACP response with unknown id=%s", msg_id)
            return

        logger.debug("ACP message ignored: %s", list(msg.keys()))

    async def _handle_server_request(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        if req_id is None:
            return

        params = msg.get("params")
        logger.info("ACP server request: %s", method)

        if method == "session/request_permission":
            option_id = self._pick_permission_option(params if isinstance(params, dict) else {})
            result = permission_response(option_id)
            await self._write(build_response(int(req_id), result))
            return

        if method == "cursor/ask_question":
            if not isinstance(params, dict):
                return
            questions = params.get("questions")
            if not isinstance(questions, list):
                return
            answers: list[dict[str, Any]] = []
            for q in questions:
                if not isinstance(q, dict):
                    continue
                question_id = q.get("id")
                options = q.get("options")
                option_ids: list[str] = []
                if isinstance(options, list) and options:
                    first = options[0] if isinstance(options[0], dict) else None
                    if isinstance(first, dict) and first.get("id"):
                        option_ids = [str(first["id"])]
                if question_id is not None:
                    answers.append(
                        {
                            "questionId": str(question_id),
                            "selectedOptionIds": option_ids,
                        }
                    )
            result = {
                "outcome": {
                    "outcome": "answered",
                    "answers": answers,
                }
            }
            await self._write(build_response(int(req_id), result))
            return

        if method == "cursor/create_plan":
            result = {"outcome": {"outcome": "accepted"}}
            await self._write(build_response(int(req_id), result))
            return

        logger.warning("Unhandled ACP server request: %s", method)

    def _pick_permission_option(self, params: dict[str, Any]) -> str:
        options = params.get("options")
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, dict) and opt.get("optionId") == self.permission_policy:
                    return self.permission_policy
            first = options[0] if options else None
            if isinstance(first, dict) and first.get("optionId"):
                return str(first["optionId"])
        return self.permission_policy
