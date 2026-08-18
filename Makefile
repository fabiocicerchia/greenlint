.PHONY: help setup install dev lint test build ext-build ext-install

EXT_DIR := editors/vscode

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install the pre-commit hook
	pre-commit install

install: ## Install the package
	pip install .

dev: ## Editable install with dev dependencies (pytest, ruff, build)
	pip install -e ".[dev]"

lint: ## Run ruff
	ruff check .

test: ## Run tests
	pytest -q

build: ## Build sdist and wheel
	python -m build

# The extension drives the installed greenlint rather than bundling it, so
# `make install` (or a pipx install) is the other half of this.
ext-build: ## Build the VS Code extension (.vsix)
	cd $(EXT_DIR) && rm -f ./*.vsix && npm ci && npm test && npm run package

ext-install: ext-build ## Build and install the VS Code extension
	@command -v code >/dev/null 2>&1 || { \
	  echo "make: the 'code' CLI is not on PATH."; \
	  echo "In VS Code run: Shell Command: Install 'code' command in PATH,"; \
	  echo "or install $(EXT_DIR)/greenlint-*.vsix from the Extensions view (... > Install from VSIX)."; \
	  exit 1; }
	code --install-extension $(EXT_DIR)/greenlint-*.vsix --force
