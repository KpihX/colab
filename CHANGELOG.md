# Changelog

All notable changes to `colab` are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- P9 prompt queue: FIFO delegate while agent busy, drain on idle, flush on stop
- CLI: `colab queue status`, `colab queue list`, `colab queue flush`
- Config: `queue.enabled`, `queue.max_size`
- P2 tmux visual: robust window index resolution, attach hints
- P3 meta catalog: ACP `available_commands_update` discovery + cache
- P4 Mistral semantic router (`json_schema` → `RouterDecision`)
- P5 `AgentRuntime`: persistent ACP session, `stop_agent` (cancel + tmux C-c)
- P6 audio foundation: energy VAD, Voxtral Realtime STT, `colab listen` loop
- P7 Voxtral TTS streaming playback + barge-in during `colab listen`
- CLI: `colab audio speak`, `colab say --speak/--no-speak`
- Config: `mistral.tts_voice_slug`, `audio.tts_sample_rate`, `audio.tts_enabled`

### Verified (live)

- `colab router/say "bonjour"` → `simple_reply`
- `colab router/say "changeons de sujet"` → `session.clear` via tmux
- `colab router/say "arrête"` → `stop_agent`

### Added (skeleton)

- Initial project skeleton under `KpihX-Labs/colab/`
- `CONTRACT.md` v0.1.0 (ACP-first, semantic router, tmux mirror, meta catalog)
- `PLAN.md` phased roadmap (P0–P10)
- `ARCHITECTURE.md` with mermaid context diagram
- Makefile aligned with `ts-proxy` (uv-check, uv-link, audit)
- Stub Python package `src/colab/` (acp, router, audio, tmux modules)

## [0.1.0] — 2026-05-26

### Added

- Project bootstrap for expert handoff (skeleton only, no runtime yet)
