"""colab error types."""

from __future__ import annotations


class ColabError(Exception):
    """Base error for colab."""


class ConfigError(ColabError):
    """Invalid or missing configuration."""


class SecretsError(ColabError):
    """Required secret not available."""


class AcpError(ColabError):
    """ACP transport or protocol failure."""


class AcpNotImplementedError(AcpError):
    """ACP method stub — implement in P1."""


class RouterError(ColabError):
    """Semantic router failure."""


class TmuxError(ColabError):
    """tmux integration failure."""


class AudioNotReadyError(ColabError):
    """Audio subsystem not implemented yet (P6+)."""
