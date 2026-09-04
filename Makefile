# greenlint — static analysis for energy-wasteful patterns.
#
# Every verb this repo exposes lives here; `make` on its own prints them,
# grouped, straight out of the `##` comments below.

EXT_DIR := extensions/vscode
# Read rather than hard-coded: vsce names the VSIX after the version in the
# manifest, so a release bump must not turn ext-install into "file not found".
EXT_VERSION := $(shell node -p "require('./$(EXT_DIR)/package.json').version" 2>/dev/null)
VSIX := $(EXT_DIR)/greenlint-$(EXT_VERSION).vsix

.DEFAULT_GOAL := help
# help is pure output; the recipe echo would only be noise.
.SILENT: help

##@ General

.PHONY: help
help: ## Show this help
	awk 'BEGIN {FS = ":.*## "} \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } \
		/^[a-zA-Z_0-9-]+:.*## / { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)

.PHONY: setup
setup: ## Install the pre-commit hook
	pre-commit install

##@ Development

.PHONY: dev
dev: ## Editable install with dev dependencies (pytest, ruff, build)
	pip install -e ".[dev]"

.PHONY: install
install: ## Install the package
	pip install .

##@ Quality

.PHONY: lint
lint: ## Run ruff
	ruff check .

.PHONY: test
test: ## Run tests
	pytest -q

# The suite guards the shape of a scan's cost; this prints the cost itself, for
# when you are changing something and want to know which way it moved.
# CORPUS=/some/big/tree make bench to point it at something larger than this repo.
.PHONY: bench
bench: ## Print what a scan costs (CORPUS=path to choose the tree)
	python3 tests/test_performance.py $(CORPUS)

##@ Release

.PHONY: build
build: ## Build sdist and wheel
	python -m build

##@ VS Code extension

# The extension drives the installed greenlint rather than bundling it, so
# `make install` (or a pipx install) is the other half of this.
#
# The same four extension verbs, with the same meanings, in gandalf, greenlint
# and depwatch: build compiles, package writes the .vsix, install side-loads it,
# publish pushes it to both marketplaces.
.PHONY: ext-build
ext-build: ## Compile the VS Code extension
	cd $(EXT_DIR) && { [ -d node_modules ] || npm install; } && npm run typecheck && npm run build

.PHONY: ext-package
ext-package: ext-build ## Build the VS Code extension into a .vsix
	cd $(EXT_DIR) && rm -f ./*.vsix && npm run package

.PHONY: ext-install
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
.PHONY: ext-publish
ext-publish: ext-package ## Publish the .vsix to both marketplaces
	cd $(EXT_DIR) && npm run publish -- --packagePath "$(notdir $(VSIX))"
	cd $(EXT_DIR) && npx --yes ovsx@1.1.1 publish "$(notdir $(VSIX))" -p "$$OVSX_PAT"
