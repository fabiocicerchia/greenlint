# greenlint

[![CI](https://github.com/fabiocicerchia/greenlint/actions/workflows/ci.yml/badge.svg)](https://github.com/fabiocicerchia/greenlint/actions/workflows/ci.yml)
[![Security](https://github.com/fabiocicerchia/greenlint/actions/workflows/security.yml/badge.svg)](https://github.com/fabiocicerchia/greenlint/actions/workflows/security.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/fabiocicerchia/greenlint/badge)](https://securityscorecards.dev/viewer/?uri=github.com/fabiocicerchia/greenlint)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Ffabiocicerchia%2Fgreenlint.svg?type=shield)](https://app.fossa.com/projects/git%2Bgithub.com%2Ffabiocicerchia%2Fgreenlint?ref=badge_shield)
[![Release](https://img.shields.io/github/v/release/fabiocicerchia/greenlint)](https://github.com/fabiocicerchia/greenlint/releases)

Static analysis that flags **energy-wasteful patterns** across languages and
configs — busy loops, sub-100ms polling, every-minute crons, `SELECT *`,
full-history CI clones, full-fat base images, peak-sized instances. Every
finding says *why it wastes energy* and what to do instead.

```console
$ greenlint src/ .github/
.github/workflows/ci.yml:12: [GL003/high] cron job scheduled every minute
    ↳ every-minute CI/cron jobs rarely need it; widen the schedule
src/db.py:44: [GL005/medium] SELECT * query
    ↳ fetch only needed columns; less I/O, less network, less RAM

greenlint: 2 finding(s)
```

## Install

```sh
pipx install git+https://github.com/fabiocicerchia/greenlint
```

Or with pip:

```sh
pip install git+https://github.com/fabiocicerchia/greenlint
```

Or the one-line installer:

```sh
curl -fsSL https://raw.githubusercontent.com/fabiocicerchia/greenlint/main/install.sh | bash
```

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

## Rules

8 seed rules across Python/JS/TS/SQL/YAML/Dockerfile/Terraform (GL001–GL008,
see `--list-rules`). Rule development is deliberately open-ended — the rule
set *is* the product. Proposals with an energy rationale are the most
valuable contribution.

## Status & roadmap

- [x] Rule engine, severity ordering, JSON output, CI gate
- [x] Per-repo config (`.greenlint.toml`: rule enable/disable, ignores)
- [ ] AST-based rules for Python/JS (regex has false-positive limits)
- [x] Estimated gCO2e annotation per finding class
- [x] Pre-commit hook + GitHub annotation output

## Development

`make setup` (git hooks + pre-commit), then `make dev` and `make test` / `make lint`.

## Documentation

Full docs live in [`docs/`](docs/) (also published via mkdocs). Runnable
examples live in [`examples/`](examples/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). By participating you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md). greenlint uses
[Conventional Commits](https://www.conventionalcommits.org/) and release-please.

## Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) — please don't open a public issue.

## License

[Apache 2.0](LICENSE) © Fabio Cicerchia
