# CONTRACT.md — colab

> **Source of truth** for operators and AI agents.
> **0% heuristic routing · semantic Mistral router · ACP-first agent path · tmux visual mirror**

Contract metadata:

- `schema_version`: `colab.contract.v1`
- `contract_version`: `0.1.1`

---

## Facet 1: PROD (Usage Contract)

### 1.1 Purpose

`colab` is a **voice orchestration layer** that:

1. Listens to the workstation microphone while the daemon runs.
2. Transcribes speech (Mistral Voxtral Realtime — planned).
3. Routes each utterance **semantically** (Mistral LLM, structured JSON — no keyword rules).
4. Either answers locally, executes a **meta-action** discovered from the agent, or **delegates** to the default ACP agent (Cursor).
5. Speaks responses (Mistral Voxtral TTS) with **barge-in** support.
6. Keeps a **visible tmux pane** attached to the same agent session for human inspection.

### 1.2 Installation

```bash
cd $HOME/KpihX-Labs/colab
make uv-link          # dev editable
# or
make uv-install     # production tool install
```

Binary: `colab` → Typer CLI (`colab.cli:app`).

### 1.3 Data locations

| Data | Path | Mode | Permission |
|------|------|------|------------|
| Config | `~/.colab/config.yaml` | persisted | `600` |
| Secrets | `~/.colab/secrets.json` or env | persisted / env | `600` |
| Glossary | `~/.colab/glossary.yaml` | persisted | `644` |
| Session state | `~/.colab/sessions/` | persisted | `700` |
| Logs | `~/.colab/colab.log` | persisted | `600` |

Package defaults ship in `src/colab/config.yaml`; user overrides merge on top.

### 1.4 CLI architecture

```text
   ╔══════════════════════╗
   ║  Operator / Voice    ║
   ╚══════════╦═══════════╝
              │
              ▼
   ╔══════════════════════╗
   ║  colab listen        ║  ← main loop (STT → router → act)
   ╚══════════╦═══════════╝
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
  LOCAL    META     DELEGATE
  reply   (ACP/     (ACP
          tmux)     session/prompt)
              │
              ▼
   ╔══════════════════════╗
   ║  tmux pane (visual)  ║  default: session `default`, window `cursor`
   ╚══════════════════════╝
```

### 1.5 CLI namespaces

| Namespace | Role |
|-----------|------|
| `colab listen` | Start continuous voice loop until SIGINT/exit command |
| `colab say <text>` | Inject text as if spoken (debug / scripting); `--speak` / `--no-speak` |
| `colab audio speak` | TTS-only smoke test |
| `colab admin` | Config, secrets, health, glossary |
| `colab agent` | ACP session lifecycle (new, prompt, cancel, status) |
| `colab tmux` | Ensure visual pane, attach hints, send-keys fallback |
| `colab meta` | List / refresh meta-actions catalog from ACP agent |
| `colab router` | Dry-run routing for a transcript (no side effects) |

### 1.6 Routing contract (semantic)

Every utterance produces a **RouterDecision** (JSON). No keyword triggers.

| `intent` | Meaning | Action |
|----------|---------|--------|
| `simple_reply` | Factual / social; no tools | Mistral chat → TTS |
| `meta_action` | Session control (clear, new topic, mode…) | Execute `action_id` from catalog |
| `delegate_agent` | Coding / tools / research | `session/prompt` on default ACP session |
| `stop_agent` | Interrupt current agent work | `session/cancel` + tmux `C-c` fallback |

Fields (Pydantic, `extra="forbid"`):

```json
{
  "intent": "delegate_agent",
  "confidence": 0.92,
  "simple_reply": null,
  "meta_action_id": null,
  "agent_prompt": "[VOICE_INPUT]…[/VOICE_INPUT]",
  "reasoning_short": "User asked to refactor module X using MCP"
}
```

### 1.7 Meta-actions catalog (ACP-driven, not hardcoded)

Meta-actions are **discovered**, not invented in colab:

1. On startup (and on `colab meta refresh`), colab interrogates the default agent:
   - CLI slash-commands exposed by `agent` / `agent acp` help surfaces.
   - Cursor ACP extension methods where applicable (`cursor/*`).
   - Optional: scrape `agent --help` / `agent help` stdout once per version.
2. Each entry is stored as:

```json
{
  "id": "session.clear",
  "labels": ["clear", "nouveau chat", "changeons de sujet"],
  "delivery": "acp_notification | tmux_send_keys",
  "payload": { "keys": "/clear", "enter": true }
}
```

The router receives the **catalog summary** in its system prompt and returns `meta_action_id` — never raw `/clear` string matching.

**Fallback:** if discovery fails, a minimal built-in catalog is loaded from `config.yaml` → `meta_actions_fallback` (documented, versioned).

### 1.8 ACP agent contract (default: Cursor)

| Requirement | Value |
|-------------|--------|
| Binary | `~/.local/bin/agent` (config: `agents.default.binary`) |
| Mode | `agent acp` subprocess, stdio NDJSON |
| Auth | Pre-login: `agent login` or `CURSOR_API_KEY` |
| Session | Persistent `sessionId` per colab run |
| Prompt wrap | `[VOICE_INPUT channel=colab lang=…]…[/VOICE_INPUT]` |
| Stream | Consume `session/update` → `agent_message_chunk` for TTS |
| Cancel | `session/cancel` on `stop_agent` |
| Permissions | Config policy: `allow-once` default for hands-free (override in config) |

Reference: [Cursor ACP docs](https://cursor.com/docs/cli/acp).

### 1.9 tmux visual contract

| Setting | Default | Purpose |
|---------|---------|---------|
| `tmux.session` | `default` | Session name |
| `tmux.window` | `cursor` | Window name |
| `tmux.launch_cmd` | `agent` | Command if pane empty |
| `tmux.attach_hint` | true | Print `tmux attach -t …` on start |

Operations:

- `ensure_pane`: create session/window/pane if missing; run `launch_cmd` if no agent process.
- `mirror_status`: optional title/format refresh (future).
- `send_keys_fallback`: only when `delivery=tmux_send_keys` in meta catalog.

Human can **always** attach to watch the same agent colab drives via ACP.

### 1.10 Audio contract (planned — see PLAN.md)

| Stage | Service | Notes |
|-------|---------|-------|
| STT | Mistral Voxtral Realtime | Streaming, glossary bias |
| TTS | Mistral Voxtral TTS | Streaming `speech.audio.delta` → float32 PCM playback |
| VAD | Energy threshold | End-of-utterance; barge-in uses same mic path |
| Barge-in | Stop TTS + resume listen | After `barge_in_ms` of sustained speech above threshold |

### 1.11 Queue contract

When `delegate_agent` arrives while agent `busy`:

- Enqueue with monotonic `turn_id`.
- On agent idle, flush queue FIFO.
- `stop_agent` clears queue head and cancels active turn.
- Stale `session/update` chunks ignored if `turn_id` mismatch.

---

## Facet 2: DEV (Development Guide)

### 2.1 Project structure

```text
colab/
├── .agents/AGENTS.md
├── scripts/
│   └── audit_infra.py
├── src/colab/
│   ├── __init__.py
│   ├── cli.py              # Typer entry
│   ├── config.py           # YAML + secrets
│   ├── config.yaml
│   ├── exceptions.py
│   ├── model.py            # Pydantic contracts
│   ├── orchestrator.py     # listen loop (skeleton)
│   ├── acp/
│   │   ├── client.py       # JSON-RPC stdio
│   │   ├── session.py      # session lifecycle
│   │   └── meta.py         # meta-action discovery
│   ├── router/
│   │   ├── mistral.py      # semantic router
│   │   └── prompts.py
│   ├── audio/
│   │   ├── stt.py
│   │   ├── tts.py
│   │   └── vad.py
│   └── tmux/
│       └── pane.py
├── tests/
├── CONTRACT.md             # this file
├── PLAN.md
├── ARCHITECTURE.md
├── README.md
├── TODO.md
├── CHANGELOG.md
├── Makefile
└── pyproject.toml
```

### 2.2 Mandatory commands

| Command | Role |
|---------|------|
| `make uv-check` | format → fix → compile → audit → test |
| `make check` | uv-check + infra audit |
| `make uv-link` | editable install |

### 2.3 Implementation rules

1. **Contract first** — change `CONTRACT.md` before public behavior.
2. **No heuristic routing** — only structured LLM output + catalog IDs.
3. **ACP before tmux** — tmux is mirror + fallback, not primary transport.
4. **No secrets in logs** — redact API keys and auth tokens.
5. **Alphabetical order** in registries (`meta.py`, CLI command tables) where applicable.

### 2.4 Related KπX projects

| Project | Relationship |
|---------|----------------|
| `$HOME/Work/AI/flow/` | STT kernel / audio normalization reuse candidate |
| `$HOME/KpihX-Labs/Fluid/ts_proxy/` | Makefile + CONTRACT pattern |
| `k-tmux`, `k-zed` | tmux + ACP skills |

---

## Changelog (contract)

| Version | Change |
|---------|--------|
| 0.1.1 | P7 TTS + barge-in; `colab audio speak`; `say --speak` |
| 0.1.0 | Initial skeleton contract |
