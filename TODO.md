# TODO — colab

> Sync with [PLAN.md](PLAN.md). Mark done when phase exit criteria met.

## P0 — Scaffold

- [x] Repo layout under `$HOME/KpihX-Labs/colab/`
- [x] CONTRACT, PLAN, ARCHITECTURE, README
- [x] Makefile (ts-proxy style)
- [x] `uv sync` + `make uv-check` green
- [ ] Git remote init (operator)

## P1 — ACP core

- [x] `AcpClient` NDJSON stdio
- [x] `initialize` / `authenticate` / `session/new`
- [x] `session/prompt` + stream parser
- [x] `session/cancel`
- [x] Permission handler (config policy)
- [x] Fixture tests

## P2 — tmux visual

- [x] `ensure_pane`
- [x] Launch `agent` if missing
- [x] Attach hint on start

## P3 — Meta catalog

- [x] `discover_meta_actions`
- [x] Cache `~/.colab/meta_catalog.json`
- [x] `colab meta list|refresh`

## P4 — Router

- [x] Mistral structured `RouterDecision`
- [x] `colab router` dry-run
- [x] Mocked LLM tests (`test_router_mistral.py` — 15 tests)

## P5 — Meta execution

- [x] Execute by `action_id`
- [x] Stop → cancel + C-c (`AgentRuntime.stop_agent`)

## P6–P8 — Audio + orchestrator

- [x] Voxtral STT module + energy VAD (optional `colab[audio]`)
- [x] `colab listen` loop (mic → STT → handle_text → TTS + barge-in)
- [x] Voxtral TTS + barge-in (P7)
- [x] Full voice E2E soak test (`test_orchestrator_e2e.py` — 10 tests)

## P9 — Queue

- [x] `PromptQueue` FIFO + monotonic `turn_id`
- [x] Enqueue when `delegate_agent` and agent busy
- [x] Drain queue after each turn completes
- [x] `stop_agent` / `STOP_AGENT` flush queue
- [x] CLI: `colab queue status|list|flush`
- [x] Config: `queue.enabled`, `queue.max_size`

## P10

- [x] Soak test + k-context entry
