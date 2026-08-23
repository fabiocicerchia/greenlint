# greenlint.nvim

Flags energy-wasteful code and config as you work, with the reason each one
wastes energy.

greenlint has 38 rules — busy loops, sub-100ms polling, every-minute crons,
`SELECT *`, full-history CI clones, oversized instances, quadratic rebuilds,
missing log retention — each with a concrete "do instead" and a CO₂e hint whose
arithmetic is documented against one stated model.

```
while True:        ⚠ busy loop without sleep — poll with a backoff/sleep, or use an event-driven wait
    pass
```

The rule set **is** the product, so this plugin does not reimplement it.
greenlint is Python regexes plus six `ast`-based analyses; a Lua rewrite would
be a different linter that mostly agrees, which is the worst possible outcome.
The CLI is run instead — ~60ms for a file, ~120ms for a small repository,
interpreter start included, which is what makes that affordable.

## Requirements

- Neovim **0.11+**
- the `greenlint` CLI (`pip install greenlint`), or a `greenlint.py` checkout
- [plenary.nvim](https://github.com/nvim-lua/plenary.nvim) — for `make test` only

`:checkhealth greenlint` reports on all of it, including how many rules your
build has.

## Install

The plugin lives in `extensions/nvim/` of the greenlint repository.

**lazy.nvim**

```lua
{
  'fabiocicerchia/greenlint',
  rtp = 'extensions/nvim',
  event = { 'BufReadPost', 'BufNewFile' },
  cmd = { 'GreenlintScan', 'GreenlintReport' },
  opts = {},
}
```

**vim-plug**

```vim
Plug 'fabiocicerchia/greenlint', { 'rtp': 'extensions/nvim' }
```

```lua
require('greenlint').setup({})
```

Against a checkout rather than an installed release:

```lua
require('greenlint').setup({ cmd = { 'python3', '/path/to/greenlint.py' } })
```

## Configuration

```lua
require('greenlint').setup({
  enabled = true,
  cmd = { 'greenlint' },

  -- on_save | on_type | manual
  run = 'on_save',
  debounce_ms = 400,

  scan_project_on_startup = true,
  max_file_bytes = 1000000,

  -- Extra ignore globs for the editor only, on top of .greenlint.toml.
  exclude = {},
  timeout_ms = 60000,

  diagnostics = {
    enabled = true,
    severity = {
      high   = vim.diagnostic.severity.WARN,
      medium = vim.diagnostic.severity.INFO,
      low    = vim.diagnostic.severity.HINT,
    },
  },

  grouping = 'file',  -- severity | file | rule
})
```

`.greenlint.toml` and `.greenlint-baseline.json` in the project root are picked
up automatically and passed as `--config` / `--baseline`, so the editor and CI
honour the same rule opt-outs and the same accepted findings.

### `run = 'on_type'`

Scans the buffer as you go, debounced. The CLI reads files rather than buffers,
so the buffer is written to a temp file first — keeping its basename, because
greenlint picks a rule set by extension and recognises a test file by its name.
An answer that arrives after a newer edit is discarded rather than shown.

## Commands

| Command | What it does |
| --- | --- |
| `:GreenlintScan` | Scan the current file (unsaved buffers included) |
| `:GreenlintScanProject` | Scan the whole project |
| `:GreenlintReport` | The report, in a float |
| `:GreenlintList` | Every finding, in the quickfix list |
| `:GreenlintFilter` | Findings at one severity |
| `:GreenlintGroupBy` | Group the report by file, severity or rule |
| `:GreenlintHover` | Explain the finding under the cursor |
| `:GreenlintBaselineWrite` | Accept every current finding (asks first) |
| `:GreenlintLog` | What was run, and what came back |

## Statusline

```lua
require('lualine').setup({
  sections = { lualine_x = { { require('greenlint').statusline } } },
})
```

Reads `󱄅 0/2/0` — high, medium and low counts. Empty when nothing was found.

## Differences from the VS Code extension

The VS Code extension ships a long-lived Python scan server that imports
greenlint and calls its functions, with a stat/hash cache behind it. That is
genuinely good engineering, and it is more than a plugin needs: at 60ms a file,
running the CLI is fast enough, and one fewer moving part is worth more than the
milliseconds.

The consequences, stated rather than hidden:

| Lost | What it means |
| --- | --- |
| stat/hash cache | The server skips unchanged files without opening them; here every scan reads what it scans. A whole small repository is ~120ms, so this only bites on a very large tree — scan a file rather than the project when it does |
| streaming batches | A project scan appears all at once instead of filling in as it walks |
| `pythonPath` + `greenlintPath` | One `cmd` list replaces both |
| `trace` | `:GreenlintLog` always records what ran |
| `restartServer` | There is no server to restart |
| `respectEditorExcludes` | Neovim has no `files.exclude` / `search.exclude` to translate — use `exclude`, or `.greenlint.toml` |

**Different**

- **Findings pane** → the quickfix list and a float, rather than a tree view.
- **Hover** → `:GreenlintHover`, on request, so it never competes with your LSP.

## A note on ordering

The plugin sorts findings, because it merges results from several scans and no
single greenlint run covers that. But *which* order that is belongs to
greenlint, so `tests/severity_order_spec.lua` reads `greenlint.py` and fails if
the copy here ever stops matching `SEVERITY_ORDER`.

## Development

```sh
make test    # 35 specs, headless, exactly as CI runs them
```

`tests/smoke.lua` drives the plugin against the real CLI and real files.

## License

Apache-2.0, with the rest of greenlint.
