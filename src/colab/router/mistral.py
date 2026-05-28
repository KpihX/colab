"""Mistral semantic router — structured JSON output.

P4 implementation:
- If `MISTRAL_API_KEY` is missing, fall back to a deterministic `delegate_agent`.
- If `MISTRAL_API_KEY` is present, call Mistral `POST /v1/chat/completions`
  with `response_format=json_schema` to force a schema-valid RouterDecision.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from colab.config import get_secret, load_config
from colab.exceptions import RouterError, SecretsError
from colab.model import MetaCatalog, RouterDecision, RouterIntent
from colab.router.prompts import ROUTER_SYSTEM

logger = logging.getLogger(__name__)


def _catalog_summary(catalog: MetaCatalog | None) -> str:
    if catalog is None or not catalog.actions:
        return "(empty — use delegate_agent for ambiguous cases)"
    # Keep prompt compact: prioritize explicit session meta actions.
    limit = int(load_config().get("router", {}).get("max_catalog_actions", 30))
    actions = sorted(catalog.actions, key=lambda a: 0 if a.id.startswith("session.") else 1)
    lines: list[str] = []
    for a in actions[:limit]:
        labels = ", ".join(a.labels[:4])
        desc = (a.description or "").strip()
        if len(desc) > 120:
            desc = desc[:117] + "…"
        lines.append(f"- {a.id}: {desc} (e.g. {labels})")
    return "\n".join(lines)


def _build_router_json_schema() -> dict[str, Any]:
    """Schema for Mistral json_schema strict output."""
    # Note: RouterDecision fields must be exactly representable and typed.
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string", "enum": [i.value for i in RouterIntent]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "simple_reply": {"type": ["string", "null"]},
            "meta_action_id": {"type": ["string", "null"]},
            "agent_prompt": {"type": ["string", "null"]},
            "reasoning_short": {"type": ["string", "null"]},
        },
        "required": [
            "intent",
            "confidence",
            "simple_reply",
            "meta_action_id",
            "agent_prompt",
            "reasoning_short",
        ],
    }


def route_transcript(
    transcript: str,
    catalog: MetaCatalog | None = None,
) -> RouterDecision:
    """Classify transcript into a RouterDecision."""
    cfg = load_config()
    wrapper = cfg["router"].get("voice_prompt_wrapper", "{transcript}")

    try:
        api_key_env = cfg["mistral"]["api_key_env"]
        api_key = get_secret(api_key_env)
    except SecretsError:
        # For unit tests & offline dev: deterministic fallback.
        prompt = wrapper.format(transcript=transcript)
        return RouterDecision(
            intent=RouterIntent.DELEGATE_AGENT,
            confidence=0.0,
            agent_prompt=prompt,
            reasoning_short="no MISTRAL_API_KEY — fallback to delegate_agent",
        )

    system_prompt = ROUTER_SYSTEM.format(catalog_summary=_catalog_summary(catalog))
    user_prompt = wrapper.format(transcript=transcript)

    payload: dict[str, Any] = {
        "model": cfg["mistral"]["router_model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "colab_router",
                "schema": _build_router_json_schema(),
                "strict": True,
            },
        },
    }

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with httpx.Client(timeout=25.0) as client:
            res = client.post(url, json=payload, headers=headers)
        res.raise_for_status()
        data = res.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise RouterError("Mistral returned non-string content")
        decoded = json.loads(content)
        return RouterDecision.model_validate(decoded)
    except (httpx.HTTPError, json.JSONDecodeError, IndexError, RouterError) as exc:
        logger.warning("Router Mistral failure; fallback to delegate_agent: %s", exc)
        prompt = wrapper.format(transcript=transcript)
        return RouterDecision(
            intent=RouterIntent.DELEGATE_AGENT,
            confidence=0.0,
            agent_prompt=prompt,
            reasoning_short=f"router failed ({type(exc).__name__}) — delegate_agent fallback",
        )
