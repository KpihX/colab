"""Contract model tests."""

from colab.model import MetaAction, MetaCatalog, MetaDelivery, RouterDecision, RouterIntent


def test_router_decision_forbids_extra() -> None:
    d = RouterDecision(
        intent=RouterIntent.SIMPLE_REPLY,
        confidence=1.0,
        simple_reply="bonjour",
    )
    assert d.intent == RouterIntent.SIMPLE_REPLY


def test_meta_catalog_roundtrip() -> None:
    catalog = MetaCatalog(
        agent_binary="/usr/bin/agent",
        actions=[
            MetaAction(
                id="session.clear",
                description="clear",
                delivery=MetaDelivery.TMUX_SEND_KEYS,
                payload={"keys": "/clear"},
            )
        ],
    )
    raw = catalog.model_dump_json()
    restored = MetaCatalog.model_validate_json(raw)
    assert restored.actions[0].id == "session.clear"
