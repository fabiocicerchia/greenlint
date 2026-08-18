.PHONY: help setup install dev lint test build ext-build ext-package ext-install ext-publish

EXT_DIR := editors/vscode
# Read rather than hard-coded: vsce names the VSIX after the version in the
# manifest, so a release bump must not turn ext-install into "file not found".
EXT_VERSION := $(shell node -p "require('./$(EXT_DIR)/package.json').version" 2>/dev/null)
VSIX := $(EXT_DIR)/greenlint-$(EXT_VERSION).vsix

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
#
# The same four extension verbs, with the same meanings, in gandalf, greenlint
# and depwatch: build compiles, package writes the .vsix, install side-loads it,
# publish pushes it to both marketplaces.
ext-build: ## Compile the VS Code extension
	cd $(EXT_DIR) && { [ -d node_modules ] || npm install; } && npm run typecheck && npm run build

ext-package: ext-build ## Build the VS Code extension into a .vsix
	cd $(EXT_DIR) && rm -f ./*.vsix && npm run package

ext-install: ext-package ## Build the VS Code extension and install it
	@command -v code >/dev/null 2>&1 || { \
	  echo "make: the 'code' CLI is not on PATH."; \
	  echo "In VS Code run: Shell Command: Install 'code' command in PATH,"; \
	  echo "or install $(VSIX) from the Extensions view (... > Install from VSIX)."; \
	  exit 1; }
	code --install-extension $(VSIX) --force

# Normally CI's business: publishing happens in publish-extension.yml, called by
# release.yml when release-please cuts a release. This is the manual escape
# hatch, and it needs VSCE_PAT and OVSX_PAT in the environment.
ext-publish: ext-package ## Publish the .vsix to both marketplaces
	cd $(EXT_DIR) && npm run publish -- --packagePath "$(notdir $(VSIX))"
	cd $(EXT_DIR) && npx --yes ovsx@1.1.1 publish "$(notdir $(VSIX))" -p "$$OVSX_PAT"
