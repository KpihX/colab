# AGENTS.md — colab

## KπX mantras

**Exploration:** Problem First → Why before How  
**Architecture:** 0 Trust · 100% Control | 0 Magic · 100% Transparency | 0 Hardcoding · 100% Flexibility

## Project overview

| Field | Value |
|-------|-------|
| Purpose | Voice orchestration: Mistral semantic router + ACP agents + tmux visual mirror |
| Stack | Python 3.12+, uv, Typer, httpx, Pydantic |
| Status | 🟡 Skeleton — implement per `PLAN.md` |
| Contract | `CONTRACT.md` is law |

## Mandatory quality gate

> Do not declare a task finished until `make check` exits 0.

## Implementation order (strict)

1. **P1** — `src/colab/acp/` (ACP client + session)
2. **P2** — `src/colab/tmux/pane.py`
3. **P3** — `src/colab/acp/meta.py` (catalog discovery)
4. **P4** — `src/colab/router/`
5. **P5** — meta execution
6. **P6–P8** — audio + orchestrator

Do **not** implement heuristic routing (keyword lists for intents).

## Skills to load

| Skill | When |
|-------|------|
| `k-project` | Structure / config changes |
| `k-tmux` | tmux send-keys, session naming |
| `k-zed` | ACP protocol reference |
| `k-codex` | Cursor `agent` CLI paths |
| `k-final` | Release closure |

## Key paths

- Repo: `$HOME/KpihX-Labs/colab/`
- User data: `~/.colab/`
- Default agent binary: `~/.local/bin/agent`
- Default tmux: session `default`, window `cursor`

## References

- Cursor ACP: https://cursor.com/docs/cli/acp
- Prior art: `flow` (STT), `ts_proxy` (CONTRACT/Makefile), VoxCode/claude-talk (tmux voice)
