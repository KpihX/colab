"""Pydantic contracts — see CONTRACT.md."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class RouterIntent(StrEnum):
    SIMPLE_REPLY = "simple_reply"
    META_ACTION = "meta_action"
    DELEGATE_AGENT = "delegate_agent"
    STOP_AGENT = "stop_agent"


class RouterDecision(StrictModel):
    """Semantic routing output — no keyword matching in code."""

    intent: RouterIntent
    confidence: float = Field(ge=0.0, le=1.0)
    simple_reply: str | None = None
    meta_action_id: str | None = None
    agent_prompt: str | None = None
    reasoning_short: str | None = None


class MetaDelivery(StrEnum):
    ACP_NOTIFICATION = "acp_notification"
    TMUX_SEND_KEYS = "tmux_send_keys"


class MetaAction(StrictModel):
    """Discovered or configured meta-action."""

    id: str
    description: str
    labels: list[str] = Field(default_factory=list)
    delivery: MetaDelivery
    payload: dict[str, Any] = Field(default_factory=dict)


class MetaCatalog(StrictModel):
    schema_version: Literal["colab.meta_catalog.v1"] = "colab.meta_catalog.v1"
    agent_binary: str
    agent_version_hash: str | None = None
    discovered_at: str | None = None
    actions: list[MetaAction] = Field(default_factory=list)


class AgentChunk(StrictModel):
    """Normalized streaming chunk from ACP session/update."""

    text: str
    is_final: bool = False
    turn_id: str | None = None


class SessionState(StrictModel):
    """Persisted colab ↔ ACP session binding."""

    session_id: str
    cwd: str
    agent_name: str = "default"
    mode: str = "agent"
