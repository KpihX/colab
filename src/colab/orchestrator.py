"""Main listen loop — wires STT → router → ACP/tmux → TTS."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from rich.console import Console

from colab.acp.meta import discover_meta_actions, execute_meta_action, load_catalog
from colab.acp.session import AcpSession
from colab.audio.tts import listen_tts_enabled
from colab.config import get_agent_binary, load_config
from colab.exceptions import AudioNotReadyError
from colab.model import RouterIntent
from colab.router.mistral import route_transcript
from colab.runtime import get_runtime, reset_runtime
from colab.tmux.pane import attach_hint, ensure_pane

logger = logging.getLogger(__name__)
console = Console()

_PROMPT_TIMEOUTS = {
    "initial_timeout_s": 12.0,
    "idle_timeout_s": 3.0,
    "max_turn_time_s": 120.0,
}


def _prepare_visual() -> None:
    target = ensure_pane()
    hint = attach_hint()
    if hint:
        console.print(f"[dim]Visual mirror:[/] [cyan]{hint}[/] (pane {target})")


def run_listen() -> None:
    """Entry for `colab listen`. Uses mic when audio.enabled, else blocks with hint."""
    cfg = load_config()
    _prepare_visual()
    binary = get_agent_binary()
    runtime = get_runtime()

    if not cfg.get("audio", {}).get("enabled", False):
        console.print(
            "[yellow]Audio disabled.[/] Set [bold]audio.enabled: true[/] in "
            "~/.colab/config.yaml and install [bold]uv sync --extra audio[/]."
        )
        console.print("[dim]Use [bold]colab say <text>[/] meanwhile.[/]")
        return

    console.print("[green]Listening…[/] (Ctrl+C to stop)")
    try:
        asyncio.run(_run_listen_inner(binary, runtime))
    finally:
        reset_runtime()


async def _run_listen_inner(binary: str, runtime) -> None:
    catalog = load_catalog() or await discover_meta_actions(binary)
    _ = catalog
    _ = runtime

    shutdown_ev = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_sigint() -> None:
        console.print("\n[dim]Shutting down colab…[/]")
        from colab.audio.tts import stop_speaking

        stop_speaking()
        shutdown_ev.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_sigint)

    listen_task = asyncio.create_task(_listen_loop())
    await asyncio.wait(
        {listen_task, asyncio.create_task(shutdown_ev.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )
    listen_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listen_task


async def _speak_with_barge_in(text: str) -> bool:
    from colab.audio.barge_in import wait_for_barge_in
    from colab.audio.tts import get_tts_player

    player = get_tts_player()
    loop = asyncio.get_running_loop()

    async def _monitor() -> bool:
        if await wait_for_barge_in(player):
            player.stop_speaking()
            return True
        return False

    speak_future: asyncio.Future[object] = loop.run_in_executor(None, player.speak, text)
    monitor_task = asyncio.create_task(_monitor())
    done, pending = await asyncio.wait(
        {speak_future, monitor_task},  # type: ignore[arg-type]
        return_when=asyncio.FIRST_COMPLETED,
    )

    interrupted = False
    if monitor_task in done and monitor_task.result():
        interrupted = True
        if not speak_future.done():
            await speak_future
    else:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        await speak_future

    for item in pending:
        item.cancel()
    return interrupted


async def _listen_loop() -> None:
    from colab.audio.stt import transcribe_pcm
    from colab.audio.tts import get_tts_player
    from colab.audio.vad import VoiceActivityDetector

    vad = VoiceActivityDetector()

    while True:
        if get_tts_player().is_speaking:
            await asyncio.sleep(0.05)
            continue

        console.print("[dim]… waiting for speech[/]")
        pcm = await vad.capture_utterance()
        if not pcm:
            continue

        console.print("[cyan]transcribing…[/]")
        try:
            transcript = await transcribe_pcm(pcm)
        except (AudioNotReadyError, Exception) as exc:
            console.print(f"[red]STT error:[/] {exc}")
            continue

        if not transcript.strip():
            continue

        console.print(f"[bold]heard:[/] {transcript}")
        speeches = await handle_text(transcript)

        if listen_tts_enabled():
            for response_text in speeches:
                if not response_text:
                    continue
                interrupted = await _speak_with_barge_in(response_text)
                if interrupted:
                    console.print("[yellow]barge-in[/] — listening again")
                    break


async def _run_agent_prompt(session: AcpSession, prompt_text: str) -> str:
    parts: list[str] = []
    async for chunk in session.prompt(prompt_text, voice_wrap=True, **_PROMPT_TIMEOUTS):
        if chunk.text:
            console.print(chunk.text, end="")
            parts.append(chunk.text)
    console.print()
    return "".join(parts).strip()


async def _drain_delegate_queue(runtime, session: AcpSession) -> list[str]:
    speeches: list[str] = []
    while True:
        item = runtime.pop_queued()
        if item is None:
            break
        turn_id = runtime.try_begin_turn()
        if turn_id is None:
            logger.warning("Could not start queued turn %s — agent busy", item.turn_id)
            runtime.requeue_front(item)
            break
        console.print(f"[dim]queue[/] running {item.turn_id}")
        try:
            out = await _run_agent_prompt(session, item.prompt_text)
            if out:
                speeches.append(out)
        finally:
            runtime.end_turn()
    return speeches


async def _delegate_with_queue(
    runtime,
    session: AcpSession,
    prompt_text: str,
    transcript: str,
) -> list[str]:
    speeches: list[str] = []
    turn_id = runtime.try_begin_turn()
    if turn_id is not None:
        console.print(f"[dim]turn[/] {turn_id}")
        try:
            out = await _run_agent_prompt(session, prompt_text)
            if out:
                speeches.append(out)
        finally:
            runtime.end_turn()
        speeches.extend(await _drain_delegate_queue(runtime, session))
        return speeches

    if not runtime.is_queue_enabled():
        console.print("[red]agent busy — prompt dropped (queue disabled)[/]")
        return speeches

    queued_id = runtime.enqueue_delegate(prompt_text, transcript)
    if queued_id is None:
        console.print("[red]queue full — prompt dropped[/]")
        return speeches

    console.print(
        f"[yellow]queued[/] {queued_id} (depth={runtime.queue_depth()}, waiting for agent)"
    )
    return speeches


async def handle_text(transcript: str) -> list[str]:
    """Process one utterance. Returns texts to speak aloud (in order) — async."""
    _prepare_visual()

    catalog = load_catalog() or discover_meta_actions(get_agent_binary())
    decision = route_transcript(transcript, catalog)
    runtime = get_runtime()
    speeches: list[str] = []

    console.print(
        f"[bold]intent[/]=[cyan]{decision.intent.value}[/] conf={decision.confidence:.2f}"
    )
    if decision.reasoning_short:
        console.print(f"[dim]{decision.reasoning_short}[/]")

    if decision.intent == RouterIntent.SIMPLE_REPLY and decision.simple_reply:
        console.print(decision.simple_reply)
        speeches.append(decision.simple_reply)
        return speeches

    if decision.intent == RouterIntent.META_ACTION and decision.meta_action_id:
        execute_meta_action(decision.meta_action_id, catalog)
        console.print(f"[green]meta[/] executed: {decision.meta_action_id}")
        return speeches

    if decision.intent == RouterIntent.STOP_AGENT:
        from colab.audio.tts import stop_speaking

        stop_speaking()
        flushed = runtime.flush_queue()
        if flushed:
            console.print(f"[dim]flushed {len(flushed)} queued prompt(s)[/]")
        runtime.stop_agent(catalog)
        console.print("[red]stop[/] sent (ACP cancel + tmux C-c)")
        return speeches

    if decision.intent == RouterIntent.DELEGATE_AGENT:
        prompt_text = decision.agent_prompt or transcript
        session = await runtime.ensure_connected()
        speeches.extend(await _delegate_with_queue(runtime, session, prompt_text, transcript))
        return speeches

    return speeches


async def get_session_for_cli() -> AcpSession:
    """CLI helper — reuse runtime session when possible."""
    return await get_runtime().ensure_connected()
