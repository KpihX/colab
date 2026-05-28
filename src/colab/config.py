"""Configuration loader — YAML merge + secrets."""

from __future__ import annotations

import copy
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from colab.exceptions import ConfigError, SecretsError

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).parent
_DEFAULT_YAML = _PKG_DIR / "config.yaml"
_USER_DIR = Path.home() / ".colab"
_USER_YAML = _USER_DIR / "config.yaml"

REQUIRED_SECRETS: list[str] = ["MISTRAL_API_KEY"]


def get_version() -> str:
    """Read version from pyproject.toml without hardcoding."""
    pyproject = _PKG_DIR.parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return "0.0.0"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def _expand_path(value: str) -> str:
    return str(Path(value).expanduser())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected mapping in {path}")
    return data


def ensure_data_dir() -> Path:
    """Create ~/.colab with restrictive permissions."""
    _USER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return _USER_DIR


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Merged package defaults + user overrides."""
    cfg = _load_yaml(_DEFAULT_YAML)
    user = _load_yaml(_USER_YAML)
    return _deep_merge(cfg, user)


def get_secret(name: str) -> str:
    """Resolve secret from environment (dotenv loaded on first call).

    Priority: env > ~/.colab/.env > src/colab/.env (dev template).
    """
    load_dotenv(_PKG_DIR / ".env", override=False)
    load_dotenv(_USER_DIR / ".env", override=True)
    val = os.environ.get(name)
    if not val:
        raise SecretsError(f"Missing secret: {name}")
    return val


def get_agent_binary() -> str:
    agents = load_config().get("agents", {})
    default = agents.get("default", {})
    binary = default.get("binary", "~/.local/bin/agent")
    return _expand_path(binary)


def get_tmux_target() -> tuple[str, str]:
    tmux = load_config().get("tmux", {})
    return tmux.get("session", "default"), tmux.get("window", "cursor")
