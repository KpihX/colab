"""Config loader tests."""

from colab.config import load_config


def test_load_config_has_agents_default() -> None:
    cfg = load_config()
    assert "agents" in cfg
    assert "default" in cfg["agents"]
    assert cfg["tmux"]["session"] == "default"
