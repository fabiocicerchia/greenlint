# Getting Started

## Prerequisites

- Python 3.10+
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
