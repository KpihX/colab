"""colab Typer CLI."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

import typer
from rich.console import Console

from colab import __version__
from colab.acp.meta import discover_meta_actions, load_catalog
from colab.config import ensure_data_dir, get_agent_binary, load_config
from colab.orchestrator import get_session_for_cli, handle_text, run_listen
from colab.router.mistral import route_transcript
from colab.runtime import get_runtime
from colab.tmux.pane import attach_hint, ensure_pane

app = typer.Typer(
    name="colab",
    help="Voice orchestration for ACP coding agents (Cursor).",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging")] = False,
) -> None:
    _setup_logging(verbose)


@app.command()
def version() -> None:
    """Print package version."""
    console.print(f"colab {__version__} (contract 0.1.1)")


@app.command()
def listen() -> None:
    """Start voice loop (requires audio stack — P6+)."""
    run_listen()


@app.command("say")
def say(
    text: Annotated[str, typer.Argument(help="Utterance text (simulates STT output)")],
    speak: Annotated[
        bool,
        typer.Option("--speak/--no-speak", help="Play TTS for spoken replies"),
    ] = True,
) -> None:
    """Route a single transcript through the pipeline (no microphone)."""
    speeches = asyncio.run(handle_text(text))
    if speak and speeches:
        from colab.audio.tts import speak as tts_speak

        for line in speeches:
            if line:
                tts_speak(line)


audio_app = typer.Typer(help="Audio utilities")
app.add_typer(audio_app, name="audio")


@audio_app.command("speak")
def audio_speak(
    text: Annotated[str, typer.Argument(help="Text to read aloud")],
) -> None:
    """Test TTS playback only."""
    from colab.audio.tts import speak as tts_speak

    ok = tts_speak(text)
    if not ok:
        console.print("[yellow]Playback interrupted[/]")


router_app = typer.Typer(help="Semantic routing dry-run")
app.add_typer(router_app, name="router")


@router_app.callback(invoke_without_command=True)
def router_cmd(
    text: Annotated[str | None, typer.Argument(help="Transcript")] = None,
) -> None:
    if text is None:
        raise typer.BadParameter("Provide transcript text")
    catalog = load_catalog()
    decision = route_transcript(text, catalog)
    console.print(decision.model_dump_json())


agent_app = typer.Typer(help="ACP session controls")
app.add_typer(agent_app, name="agent")


@agent_app.command("status")
def agent_status() -> None:
    """ACP subprocess and session status."""
    binary = get_agent_binary()
    from pathlib import Path

    exists = Path(binary).exists()
    console.print(f"binary={binary} exists={exists}")
    console.print("[dim]Use `colab agent prompt` to open a session.[/]")


@agent_app.command("prompt")
def agent_prompt(
    text: Annotated[str, typer.Argument(help="Prompt text for the ACP session")],
    no_wrap: Annotated[
        bool,
        typer.Option("--no-wrap", help="Skip [VOICE_INPUT] wrapper"),
    ] = False,
) -> None:
    """Send one prompt over ACP and print streamed agent text."""

    async def _run() -> None:
        session = await get_session_for_cli()
        if not session.connected:
            state = await session.connect()
            console.print(f"[dim]session={state.session_id} cwd={state.cwd}[/]")
        async for chunk in session.prompt(text, voice_wrap=not no_wrap):
            if chunk.text:
                console.print(chunk.text, end="")
        console.print()

    try:
        asyncio.run(_run())
    except Exception as exc:
        console.print(f"[red]ACP error:[/] {exc}")
        raise typer.Exit(1) from exc


@agent_app.command("cancel")
def agent_cancel() -> None:
    """Cancel in-flight ACP generation (session/cancel + tmux C-c)."""
    from colab.acp.meta import load_catalog

    catalog = load_catalog()
    if catalog is None:
        console.print("[red]No meta catalog — run `colab meta refresh`[/]")
        raise typer.Exit(1)
    get_runtime().stop_agent(catalog)
    console.print("[green]Cancel sent[/]")


tmux_app = typer.Typer(help="tmux visual mirror")
app.add_typer(tmux_app, name="tmux")


@tmux_app.command("ensure")
def tmux_ensure() -> None:
    """Create/ensure tmux session+window for agent."""
    target = ensure_pane()
    hint = attach_hint()
    console.print(f"[green]OK[/] target={target}")
    if hint:
        console.print(f"Attach: [cyan]{hint}[/]")


queue_app = typer.Typer(help="Delegate prompt queue")
app.add_typer(queue_app, name="queue")


@queue_app.command("status")
def queue_status() -> None:
    """Show queue depth and active turn."""
    runtime = get_runtime()
    console.print(f"enabled={runtime.is_queue_enabled()} depth={runtime.queue_depth()}")
    if runtime.busy:
        console.print(f"agent=busy turn={runtime.active_turn_id}")
    else:
        console.print("agent=idle")


@queue_app.command("list")
def queue_list() -> None:
    """List queued delegate prompts."""
    runtime = get_runtime()
    items = runtime.queue_snapshot()
    if not items:
        console.print("[dim]Queue empty[/]")
        return
    for item in items:
        preview = item.prompt_text[:60].replace("\n", " ")
        console.print(f"[bold]{item.turn_id}[/] — {preview!r}…")


@queue_app.command("flush")
def queue_flush() -> None:
    """Drop all queued prompts without running them."""
    flushed = get_runtime().flush_queue()
    console.print(f"[green]Flushed {len(flushed)} item(s)[/]")


meta_app = typer.Typer(help="Meta-action catalog")
app.add_typer(meta_app, name="meta")


@meta_app.command("list")
def meta_list() -> None:
    """List discovered meta-actions."""
    catalog = load_catalog()
    if catalog is None:
        console.print("[dim]No cache — run `colab meta refresh`[/]")
        raise typer.Exit(1)
    for action in catalog.actions:
        console.print(f"[bold]{action.id}[/] — {action.description}")
        console.print(f"  delivery={action.delivery.value} labels={action.labels}")


@meta_app.command("refresh")
def meta_refresh() -> None:
    """Discover meta-actions from agent and cache."""
    binary = get_agent_binary()
    catalog = asyncio.run(discover_meta_actions(binary))
    console.print(f"[green]Cached {len(catalog.actions)} actions[/]")


admin_app = typer.Typer(help="Admin & config")
app.add_typer(admin_app, name="admin")


@admin_app.command("config")
def admin_config() -> None:
    """Show merged config (secrets redacted)."""
    cfg = load_config()
    console.print_json(json.dumps(cfg, indent=2, default=str))


@admin_app.command("init")
def admin_init() -> None:
    """Create ~/.colab data directory."""
    path = ensure_data_dir()
    console.print(f"[green]Data dir:[/] {path}")


if __name__ == "__main__":
    app()
