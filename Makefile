# --- Dynamic Configuration (Extracted from pyproject.toml) ---
PKG_NAME     := $(shell grep -m 1 '^name' pyproject.toml | tr -s ' ' | tr -d '"' | tr -d "'" | cut -d' ' -f3)
PKG_DIR_NAME := $(subst -,_,$(PKG_NAME))
PKG_DIR      := src/$(PKG_DIR_NAME)
VERSION      := $(shell grep -m 1 '^version' pyproject.toml | tr -s ' ' | tr -d '"' | tr -d "'" | cut -d' ' -f3)

# --- System Paths ---
REAL_USER := $(if $(SUDO_USER),$(SUDO_USER),$(USER))
REAL_HOME := $(shell getent passwd $(REAL_USER) | cut -d: -f6)
BIN_DIR   := $(REAL_HOME)/.local/bin
DATA_DIR  := $(REAL_HOME)/.colab

# --- Tooling ---
UV     := $(shell command -v uv 2>/dev/null || echo uv)
PYTHON := $(UV) run python
PYTEST := $(PYTHON) -m pytest

.PHONY: help uv-audit uv-format uv-fix uv-compile uv-test uv-check uv-install uv-link uv-unlink uv-uninstall git-init-hooks git-commit git-tag git-push uv-build audit check

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- UV (Local Dev) ---

uv-audit: ## Run linting and style checks (Ruff)
	@echo "🔍 Running static analysis on $(PKG_DIR)..."
	@$(UV) run ruff check $(PKG_DIR) tests/

uv-format: ## Auto-format code (Ruff)
	@echo "🎨 Formatting code..."
	@$(UV) run ruff format $(PKG_DIR) tests/

uv-fix: ## Auto-fix linting issues (Ruff)
	@echo "🛠️ Auto-fixing issues..."
	@$(UV) run ruff check --fix $(PKG_DIR) tests/

uv-compile: ## Verify Python syntax compilation
	@echo "⚙️ Compiling source files..."
	@$(PYTHON) -m py_compile $(shell find $(PKG_DIR) -name "*.py")

uv-test: ## Run all tests
	@echo "🧪 Running test suite..."
	@$(PYTEST) -v tests/

uv-check: uv-format uv-fix uv-compile uv-audit uv-test ## Development quality gate

audit: ## Audit local data dir permissions (~/.colab)
	@echo "🛡️ Auditing $(DATA_DIR)..."
	@$(PYTHON) scripts/audit_infra.py

check: uv-check audit ## Full Sovereign Gate

uv-install: ## Install locally using uv tool
	@echo "📦 Installing $(PKG_NAME) v$(VERSION)..."
	@$(UV) tool install . --force

uv-link: ## Editable dev install
	@echo "🔗 Linking $(PKG_NAME) for dev..."
	@$(UV) tool install --editable . --force

uv-unlink: ## Uninstall local tool
	@echo "⌫ Unlinking $(PKG_NAME)..."
	@$(UV) tool uninstall $(PKG_NAME) || true

uv-uninstall: uv-unlink ## Alias for uv-unlink

uv-build: ## Build Python sdist and wheel
	@rm -rf dist/
	@$(UV) build

# --- Git ---

git-init-hooks: ## Install git pre-commit hook (make uv-check)
	@echo "#!/bin/sh\nmake uv-check" > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "✅ Pre-commit hook installed."

git-commit: uv-check ## Commit (requires msg="...")
	@if [ -z "$(msg)" ]; then echo "❌ Use: make git-commit msg=\"...\""; exit 1; fi
	@git add .
	@git commit -m "$(msg)"

git-tag: ## Tag from pyproject version
	@git tag -a v$(VERSION) -m "Release v$(VERSION)"

git-push: ## Push branch and tags to ALL remotes
	@branch=$$(git branch --show-current); \
	for remote in $$(git remote); do \
		echo "⬆️  Pushing to $${remote}..."; \
		git push "$${remote}" "$${branch}" --tags; \
	done

push: uv-check git-add git-commit git-push ## Full push gate (add + commit + push all remotes)

git-add: ## Stage all changes
	@git add .

git-commit: ## Commit (requires msg="...")
	@if [ -z "$(msg)" ]; then echo "❌ Use: make push msg=\"...\""; exit 1; fi
	@git commit -m "$(msg)"
