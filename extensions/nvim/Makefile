# greenlint.nvim
#
# `make test` runs the specs headless, exactly as CI does.

NVIM ?= nvim
PLENARY ?= $(shell pwd)/.deps/plenary.nvim

.PHONY: help test deps lint clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

deps: $(PLENARY) ## Fetch plenary.nvim, the only test dependency

$(PLENARY):
	@mkdir -p $(dir $(PLENARY))
	git clone --depth 1 https://github.com/nvim-lua/plenary.nvim $(PLENARY)

test: deps ## Run the specs headless
	@PLENARY=$(PLENARY) $(NVIM) --headless --noplugin \
		-u tests/minimal_init.lua \
		-c "PlenaryBustedDirectory tests { minimal_init = 'tests/minimal_init.lua', sequential = true }"

lint: ## Check the Lua parses
	@for f in $$(find lua plugin tests -name '*.lua'); do \
		$(NVIM) --headless -c "luafile $$f" -c qa 2>&1 | grep -q . && echo "FAIL $$f" || true; \
	done
	@echo "ok"

clean: ## Remove fetched test dependencies
	rm -rf .deps
