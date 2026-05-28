# colab

```text
   ╔═╗╔═╗  ╔╗ ╔═╗╔╗ ╔═╗
   ║  ║    ║║ ║ ║║║ ╚═╗
   ╚═╝╚═╝  ╚╝ ╚═╝╝╚═╚═╝
   Voice × ACP × tmux
```

> Semantic voice orchestration for ACP coding agents (Cursor first).
> **Mistral router · Agent Client Protocol · visible tmux session**

Part of **KpihX-Labs**. Sovereign, local-first, no keyword routing.

## Documentation stack

| Doc | Role |
|-----|------|
| [CONTRACT.md](CONTRACT.md) | Source of truth (prod + dev) |
| [PLAN.md](PLAN.md) | Phased implementation roadmap |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Diagrams and module boundaries |
| [.agents/AGENTS.md](.agents/AGENTS.md) | AI agent instructions |
| [TODO.md](TODO.md) | Task tracking |
| [CHANGELOG.md](CHANGELOG.md) | Releases |

## Quick start (skeleton)

```bash
cd $HOME/KpihX-Labs/colab
uv sync --extra audio
make uv-link
colab --help
```

Optional extras: **`--extra audio`** installs `mistralai[realtime]` + PyAudio (STT, TTS, mic).

**Prerequisites (for full system, see PLAN.md):**

- `agent` CLI (`~/.local/bin/agent`) + `agent login`
- `tmux`
- `MISTRAL_API_KEY` in env or `~/.colab/secrets.json` (or `src/colab/.env` in dev)
- Microphone + speakers for `colab listen` (with `audio.enabled: true`)

## Try it

```bash
colab say "bonjour"              # route + print (+ TTS if audio works)
colab say "bonjour" --no-speak   # text only
colab audio speak "test TTS"     # TTS smoke test
colab listen                     # mic loop (needs audio.enabled + PyAudio)
```

## Status

**v0.1.x — P1–P7 in progress.** ACP, tmux mirror, meta catalog, Mistral router, STT/TTS skeleton, and `colab listen` loop are implemented; see `PLAN.md` for remaining queue/hardening work.

## Related projects

- [flow]($HOME/Work/AI/flow/) — STT kernel candidate
- [ts-proxy]($HOME/KpihX-Labs/Fluid/ts_proxy/) — Makefile / CONTRACT pattern
- [ai_voice]($HOME/Work/AI/ai_voice/) — whisper-overlay fork (Wayland overlay)

## License

MIT — KπX
