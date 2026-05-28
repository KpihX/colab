"""ACP protocol parsing tests."""

from colab.acp.protocol import build_request, decode_line, parse_session_update
from colab.model import AgentChunk


def test_build_request_has_jsonrpc_id() -> None:
    req = build_request(1, "initialize", {"protocolVersion": 1})
    assert req["jsonrpc"] == "2.0"
    assert req["id"] == 1
    assert req["method"] == "initialize"


def test_decode_line_roundtrip() -> None:
    line = '{"jsonrpc":"2.0","id":1,"result":{}}\n'
    msg = decode_line(line)
    assert msg["id"] == 1


def test_parse_session_update_agent_chunk() -> None:
    chunk = parse_session_update(
        {
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Hello"},
            },
        }
    )
    assert isinstance(chunk, AgentChunk)
    assert chunk.text == "Hello"


def test_parse_session_update_ignores_unknown() -> None:
    assert parse_session_update({"update": {"sessionUpdate": "plan"}}) is None
