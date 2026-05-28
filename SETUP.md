# Setup — colab

Voice orchestrator: Mistral router + ACP agents + tmux session.

## Prerequisites

- **Python** 3.12+
- **uv** package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Mistral API key** (set as `MISTRAL_API_KEY` in `.env`)
- **ACP-compatible agent binary** (e.g. Claude Code, Cline) — configured in `config.yaml`

## Installation

```bash
# Clone
git clone git@github.com:KpihX/colab.git && cd colab

# Create venv + install dependencies
uv sync

# Install CLI as a uv tool (optional — makes `colab` available globally)
uv tool install . --force
```

### Audio extras (STT / TTS / VAD / barge-in)

```bash
uv sync --extra audio
```

Required system packages on Ubuntu:

```bash
sudo apt install portaudio19-dev python3-pyaudio
```

## Configuration

Copy `.env.example` to `.env` and fill in:

```env
MISTRAL_API_KEY=<your-mistral-api-key>
```

Edit `src/colab/config.yaml` to point to your ACP agent binary.

## Usage

```bash
# Show help
colab --help

# Dry-run router with a transcript
colab router "hello, can you help me?"

# Full voice loop (mic -> STT -> router -> ACP/agent -> TTS)
colab listen

# Manage meta actions
colab meta list
colab meta refresh
```

## Development

```bash
# Full quality gate (format, lint, compile, test, audit)
make check

# Run tests only
make uv-test
```

## Project map

| Path | Purpose |
|------|---------|
| `src/colab/cli.py` | CLI entry point (Typer) |
| `src/colab/orchestrator.py` | Main listen loop |
| `src/colab/router/mistral.py` | Mistral LLM router |
| `src/colab/acp/` | ACP client + session + meta |
| `src/colab/audio/` | STT, TTS, VAD, barge-in, mic |
| `tests/` | Pytest suite (79 tests) |
