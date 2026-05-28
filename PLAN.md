# PLAN.md — colab implementation plan

> Executable roadmap for any expert agent picking up this repo.
> **Contract:** `CONTRACT.md` · **Architecture:** `ARCHITECTURE.md` · **Tasks:** `TODO.md`

---

## Vision (one paragraph)

`colab` lets Ivann operate Cursor (and future ACP agents) **hands-free by voice**: continuous listen, semantic routing via Mistral, visible tmux mirror, meta-actions discovered from the agent itself, fluent TTS with barge-in. No keyword heuristics.

---

## Phase map

| Phase | ID | Goal | Exit criteria |
|-------|-----|------|----------------|
| 0 | `P0-scaffold` | Repo + contract + CI gate | `make uv-check` green (stub tests) |
| 1 | `P1-acp-core` | ACP client + session + stream parse | `colab agent prompt "hello"` prints streamed text |
| 2 | `P2-tmux-visual` | Visible pane + ensure launch | `colab tmux ensure` + human sees `agent` in tmux |
| 3 | `P3-meta-catalog` | Discover meta-actions | `colab meta list` shows IDs + labels |
| 4 | `P4-router` | Mistral semantic router | `colab router "changeons de sujet"` → `meta_action_id` |
| 5 | `P5-meta-exec` | Execute catalog via ACP/tmux | clear/new-chat works end-to-end |
| 6 | `P6-audio-stt` | Voxtral Realtime + VAD | `colab listen` transcribes mic |
| 7 | `P7-audio-tts` | Voxtral TTS + barge-in | spoken reply + interrupt on speech |
| 8 | `P8-orchestrator` | Full `colab listen` loop | voice → route → agent → voice |
| 9 | `P9-queue` | Busy agent queue + cancel | **done** — enqueue/drain/flush |
| 10 | `P10-hardening` | Permissions, glossary, docs | `make check` + manual soak test |

---

## P0 — Scaffold (current)

**Status:** nearly done — run `make uv-check`

- [x] Directory layout
- [x] `CONTRACT.md`, `PLAN.md`, `ARCHITECTURE.md`
- [x] `Makefile` (ts-proxy style)
- [x] `pyproject.toml`, stub modules
- [x] P1 ACP client + session + fixture tests
- [ ] `make uv-check` green (operator gate)
- [ ] Git init + remotes (operator)

**Owner notes:** Do not implement audio until P1–P5 stable.

---

## P1 — ACP core

**Status:** done (2026-05-26) — `make uv-check` green; live smoke: `colab agent prompt`.

### Tasks

1. `AcpClient` subprocess: spawn `agent acp`, NDJSON read/write loop.
2. Implement: `initialize`, `authenticate`, `session/new`, `session/prompt`, `session/cancel`.
3. Parse `session/update` → yield `AgentChunk` models.
4. Handle `session/request_permission` per config policy.
5. Unit tests with recorded JSON fixtures (no live API in CI).

### Files

- `src/colab/acp/client.py` — transport
- `src/colab/acp/session.py` — high-level API
- `tests/fixtures/acp/*.jsonl`

### References

- https://cursor.com/docs/cli/acp
- Minimal Node client in Cursor docs (port to Python asyncio or threaded reader)

---

## P2 — tmux visual

### Tasks

1. `ensure_pane(session, window, launch_cmd)` using `tmux` CLI.
2. Detect existing pane vs create window/pane.
3. Print attach hint: `tmux attach -t default`.
4. Optional: `watch` title with colab state (idle/listening/agent-busy).

### Integration

- Called at start of `colab listen` and after `colab agent` subcommands.
- Same pane target as config `tmux.*`.

### kπX skill

- Load `k-tmux` for send-keys patterns and session naming.

---

## P3 — Meta catalog discovery

### Tasks

1. `discover_meta_actions(agent_binary) -> list[MetaAction]`
2. Sources (try in order):
   - `agent --help` / help text parse for `/commands`
   - ACP capability advertisement post-`initialize` (if present)
   - Static fallback from `config.yaml`
3. Persist cache: `~/.colab/meta_catalog.json` with `discovered_at` + agent version hash.
4. CLI: `colab meta list`, `colab meta refresh`

### Router integration

- Inject compact catalog into router system prompt (ids + natural language descriptions only).

---

## P4 — Semantic router

### Tasks

1. Mistral chat API with `response_format` JSON schema → `RouterDecision`.
2. System prompt: intents + catalog + examples (few-shot), **explicit ban on keyword rules**.
3. CLI: `colab router <text>` for dry-run.
4. Tests: fixture transcripts → expected intent (mock LLM).

### Config

- `mistral.router_model` (default `mistral-small-latest`)
- `mistral.api_key_env` → `MISTRAL_API_KEY`

---

## P5 — Meta execution

### Tasks

1. `execute_meta(action_id, catalog)`:
   - If `delivery=acp_*`: map to JSON-RPC method (research per action).
   - If `delivery=tmux_send_keys`: `tmux send-keys` with escaped text + Enter.
2. Wire `stop_agent` → `session/cancel` + `C-c` to pane.
3. Integration test (manual): "changeons de sujet" triggers clear.

---

## P6–P7 — Audio (implemented)

**Status (2026-05-27):** direct `mistralai[realtime]` + PyAudio — no Pipecat dependency yet.

- **P6:** `transcribe_pcm`, energy VAD, `colab listen` STT path
- **P7:** Voxtral TTS `stream=True` + `response_format=pcm` → `PcmPlayer` (float32 @ `audio.tts_sample_rate`); barge-in monitor reads mic in parallel and calls `stop_speaking()`
- **CLI:** `colab audio speak`, `colab say --speak/--no-speak`

### Option A (recommended): Pipecat + Mistral services

- Add optional dep group `[project.optional-dependencies] audio = ["pipecat-ai[mistral]"]`
- Bridge Pipecat frames → `RouterDecision` → ACP

### Option B: Integrate `flow` STT

- HTTP/ws client to local `flow` daemon for STT only; colab keeps router/ACP.

### Glossary

- `~/.colab/glossary.yaml` → passed to Voxtral context biasing API.

---

## P8 — Orchestrator

`src/colab/orchestrator.py`:

```text
loop:
  wait utterance (VAD end)
  transcript = stt.flush()
  decision = router.route(transcript, catalog, session_state)
  match decision.intent:
    simple_reply → tts.speak(...)
    meta_action → meta.execute(...)
    delegate_agent → acp.prompt(...) ; stream → tts
    stop_agent → acp.cancel() ; tts.stop()
```

State machine documented in `ARCHITECTURE.md`.

---

## P9 — Queue

- `asyncio.Queue` or threaded queue with `turn_id`.
- Agent busy flag from ACP stream (tool running / stopReason pending).
- Flush on `stop_agent`.

---

## P10 — Hardening

- Permission policy UI or config file review
- Soak test 30 min listen
- Update `k-context` project row for `colab`
- Optional: MCP tool surface (`colab-mcp`) — **out of scope for v0.1**

---

## Risk register

| Risk | Mitigation |
|------|------------|
| ACP permission blocking | Configurable auto-allow; log blocks |
| Meta discovery incomplete | Fallback catalog + manual YAML merge |
| STT latency | Streaming TTS; partial chunks |
| tmux vs ACP desync | ACP authoritative; tmux display-only |
| Mistral costs | Router uses small model; cache catalog |

---

## Definition of done (v1.0)

1. `colab listen` runs until Ctrl+C.
2. Simple question answered by voice without invoking Cursor.
3. "Refactor X in repo" delegates to Cursor via ACP; visible in tmux.
4. "Changeons de sujet" triggers meta clear via catalog id.
5. "Stop" cancels agent mid-run.
6. Speaking during TTS interrupts and accepts new command.
7. `make check` passes.

---

## Handoff checklist for next agent

1. Read `CONTRACT.md` + this file.
2. `cd $HOME/KpihX-Labs/colab && uv sync && make uv-link`
3. Implement **P1** first (ACP client tests with fixtures).
4. Then **P2** (tmux) — quick visual win for user.
5. Do not skip **P3** before wiring meta in router.
6. Update `TODO.md` + `CHANGELOG.md` each phase.
