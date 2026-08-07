# Getting Started

## Prerequisites

- Python 3.11+ (for `tomllib`, which keeps greenlint dependency-free)
- `pipx` (recommended) or `pip`

## Install

```sh
pipx install .          # from a checkout
# or
pip install greenlint   # once published to PyPI
```

## Run

```sh
greenlint .                     # scan the current repo
greenlint --list-rules          # show every rule it knows
greenlint . --fail-on-findings  # exit non-zero if anything is found (CI gate)
greenlint . --format json       # machine-readable output
```

Try it against the bundled example:

```sh
greenlint examples/basic/
```

## Development

`make setup` (git hooks + pre-commit), then `make dev` and `make test` / `make lint`.

## Usage

```sh
pipx install .
greenlint .                          # scan the repo
greenlint --list-rules               # what it knows
greenlint . --fail-on-findings       # CI gate
greenlint . --format json            # tooling integration
greenlint . --config path/to.toml    # override the .greenlint.toml lookup
```

### Config

Drop a `.greenlint.toml` in the repo root to disable rules or ignore paths:

```toml
disable = ["GL002", "GL007"]
ignore = ["vendor/*", "*/node_modules/*"]
```
