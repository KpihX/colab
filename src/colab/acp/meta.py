"""Meta-action discovery from agent surfaces (non-heuristic catalog) — async."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from colab.acp.client import AcpClient
from colab.acp.protocol import PROTOCOL_VERSION
from colab.config import ensure_data_dir, load_config
from colab.exceptions import AcpNotImplementedError
from colab.model import MetaAction, MetaCatalog, MetaDelivery

logger = logging.getLogger(__name__)


def _catalog_path() -> Path:
    return ensure_data_dir() / "meta_catalog.json"


def _agent_version_hash(binary: str) -> str:
    try:
        out = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        blob = (out.stdout or "") + (out.stderr or "")
    except OSError:
        blob = binary
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _fallback_catalog(binary: str) -> MetaCatalog:
    cfg = load_config()
    raw_actions = cfg.get("meta_actions_fallback", [])
    actions: list[MetaAction] = []
    for item in raw_actions:
        delivery = MetaDelivery(item.get("delivery", "tmux_send_keys"))
        actions.append(
            MetaAction(
                id=item["id"],
                description=item.get("description", ""),
                labels=item.get("labels", []),
                delivery=delivery,
                payload=item.get("payload", {}),
            )
        )
    return MetaCatalog(
        agent_binary=binary,
        agent_version_hash=_agent_version_hash(binary),
        discovered_at=datetime.now(UTC).isoformat(),
        actions=actions,
    )


async def discover_meta_actions(agent_binary: str) -> MetaCatalog:
    """Interrogate agent for slash commands / ACP capabilities (async)."""
    logger.info("Discovering meta-actions for %s", agent_binary)
    fallback = _fallback_catalog(agent_binary)

    cfg = load_config()
    cwd = cfg.get("agents", {}).get("default", {}).get("cwd", "~")
    cwd = str(Path(cwd).expanduser())

    actions_by_id: dict[str, MetaAction] = {a.id: a for a in fallback.actions}

    try:
        client = AcpClient(
            agent_binary,
            extra_args=["acp"],
            permission_policy="allow-once",
            request_timeout_s=30,
        )
        await client.start()
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "colab", "version": "0.1.0"},
                },
            )
            await client.request("authenticate", {"methodId": "cursor_login"})
            await client.request("session/new", {"cwd": cwd, "mcpServers": []})

            t0 = time.monotonic()
            while time.monotonic() - t0 < 6.0:
                any_msg = False
                async for msg in client.iter_notifications(timeout=0.2):
                    any_msg = True
                    if msg.get("method") != "session/update":
                        continue
                    params = msg.get("params") or {}
                    upd = params.get("update") or {}
                    if upd.get("sessionUpdate") != "available_commands_update":
                        continue
                    available = upd.get("availableCommands") or []
                    if not isinstance(available, list):
                        continue
                    for item in available:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if not isinstance(name, str) or not name:
                            continue
                        desc = item.get("description") or ""
                        action_id = f"cmd.{name}"
                        actions_by_id.setdefault(
                            action_id,
                            MetaAction(
                                id=action_id,
                                description=str(desc),
                                labels=[name],
                                delivery=MetaDelivery.TMUX_SEND_KEYS,
                                payload={"keys": f"/{name}", "enter": True},
                            ),
                        )
                if not any_msg:
                    await asyncio.sleep(0.1)
        finally:
            await client.stop()
    except Exception as exc:
        logger.warning("Meta discovery failed, using fallback: %s", exc)

    merged_actions = list(actions_by_id.values())
    catalog = MetaCatalog(
        agent_binary=agent_binary,
        agent_version_hash=_agent_version_hash(agent_binary),
        discovered_at=datetime.now(UTC).isoformat(),
        actions=merged_actions,
    )
    save_catalog(catalog)
    return catalog


def save_catalog(catalog: MetaCatalog) -> Path:
    path = _catalog_path()
    path.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


def load_catalog() -> MetaCatalog | None:
    path = _catalog_path()
    if not path.exists():
        return None
    return MetaCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def execute_meta_action(action_id: str, catalog: MetaCatalog) -> None:
    action = next((a for a in catalog.actions if a.id == action_id), None)
    if action is None:
        raise ValueError(f"Unknown meta_action_id: {action_id}")
    if action.delivery == MetaDelivery.TMUX_SEND_KEYS:
        from colab.tmux.pane import send_keys

        keys = action.payload.get("keys", "")
        enter = action.payload.get("enter", True)
        send_keys(keys, press_enter=enter)
        return
    raise AcpNotImplementedError(f"execute_meta_action delivery={action.delivery}")
