"""Ensure tmux pane exists and optionally send keys (fallback path)."""

from __future__ import annotations

import logging
import shutil
import subprocess

from colab.config import get_tmux_target, load_config
from colab.exceptions import TmuxError

logger = logging.getLogger(__name__)


def _tmux_cmd() -> str:
    path = shutil.which("tmux")
    if not path:
        raise TmuxError("tmux not found in PATH")
    return path


def _run_tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [_tmux_cmd(), *args]
    logger.debug("tmux: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def session_exists(session: str) -> bool:
    result = _run_tmux("has-session", "-t", session, check=False)
    return result.returncode == 0


def ensure_pane() -> str:
    """Create session/window if needed; launch agent in pane. TODO P2 polish.

    Returns:
        tmux target string targeting the window index: `session:window_index`
    """
    session, window = get_tmux_target()
    cfg = load_config()["tmux"]
    launch_cmd = cfg.get("launch_cmd", "agent")

    if not session_exists(session):
        _run_tmux("new-session", "-d", "-s", session, "-n", window, launch_cmd)
        logger.info("Created tmux session %s:%s", session, window)
        # Resolve below

    # Window might not exist
    result = _run_tmux("list-windows", "-t", session, "-F", "#{window_name}", check=False)
    if result.returncode == 0:
        names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        if window not in names:
            _run_tmux("new-window", "-t", session, "-n", window, launch_cmd)
            logger.info("Created window %s in session %s", window, session)

    window_index = resolve_window_index(session, window)
    if window_index is None:
        # Fallback: best effort by name (may be ambiguous if duplicates exist)
        return f"{session}:{window}"
    return f"{session}:{window_index}"


def resolve_window_index(session: str, window_name: str) -> int | None:
    """Resolve a tmux window index for the given name.

    If multiple windows share the same name, we prefer the active one.
    """
    res = _run_tmux(
        "list-windows",
        "-t",
        session,
        "-F",
        "#{window_index}|#{window_name}|#{window_active}",
        check=False,
    )
    if res.returncode != 0:
        return None
    active_match: str | None = None
    first_match: str | None = None
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        idx, name, active = parts[0], parts[1], parts[2]
        if name != window_name:
            continue
        if first_match is None:
            first_match = idx
        if active == "1":
            active_match = idx
            break
    chosen = active_match or first_match
    if chosen is None:
        return None
    try:
        return int(chosen)
    except ValueError:
        return None


def send_keys(text: str, *, press_enter: bool = True) -> None:
    """Send keys to configured pane — meta-action fallback."""
    target = ensure_pane()
    # Literal keys (e.g. C-c) vs text
    if text.startswith("C-") and len(text) <= 4:
        _run_tmux("send-keys", "-t", target, text)
    else:
        _run_tmux("send-keys", "-t", target, "-l", text)
        if press_enter:
            _run_tmux("send-keys", "-t", target, "Enter")


def attach_hint() -> str:
    """Human-readable attach command."""
    session, _ = get_tmux_target()
    if load_config()["tmux"].get("attach_hint", True):
        return f"tmux attach -t {session}"
    return ""
