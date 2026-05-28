"""ACP JSON-RPC helpers — wire format and session/update parsing."""

from __future__ import annotations

import json
from typing import Any

from colab.model import AgentChunk

PROTOCOL_VERSION = 1
JSONRPC_VERSION = "2.0"


def build_request(req_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def build_response(req_id: int, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def build_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def decode_line(line: bytes | str) -> dict[str, Any]:
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    text = text.strip()
    if not text:
        raise ValueError("empty NDJSON line")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("ACP message must be a JSON object")
    return data


def parse_session_update(params: dict[str, Any]) -> AgentChunk | None:
    """Normalize session/update notification → AgentChunk."""
    update = params.get("update")
    if not isinstance(update, dict):
        return None

    session_update = update.get("sessionUpdate")
    if session_update == "agent_message_chunk":
        content = update.get("content")
        if isinstance(content, dict):
            text = content.get("text") or ""
            if text:
                return AgentChunk(text=str(text))
    return None


def permission_response(option_id: str) -> dict[str, Any]:
    return {"outcome": {"outcome": "selected", "optionId": option_id}}
