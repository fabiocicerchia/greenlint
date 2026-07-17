# greenlint

[![CI](https://github.com/fabiocicerchia/greenlint/actions/workflows/ci.yml/badge.svg)](https://github.com/fabiocicerchia/greenlint/actions/workflows/ci.yml)
[![Security](https://github.com/fabiocicerchia/greenlint/actions/workflows/security.yml/badge.svg)](https://github.com/fabiocicerchia/greenlint/actions/workflows/security.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/fabiocicerchia/greenlint/badge)](https://securityscorecards.dev/viewer/?uri=github.com/fabiocicerchia/greenlint)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Ffabiocicerchia%2Fgreenlint.svg?type=shield)](https://app.fossa.com/projects/git%2Bgithub.com%2Ffabiocicerchia%2Fgreenlint?ref=badge_shield)
[![Release](https://img.shields.io/github/v/release/fabiocicerchia/greenlint)](https://github.com/fabiocicerchia/greenlint/releases)

Static analysis that flags **energy-wasteful patterns** across languages and
configs — busy loops, sub-100ms polling, every-minute crons, `SELECT *`,
full-history CI clones, full-fat base images, peak-sized instances, oversized
autoscaling groups, missing Kubernetes/docker-compose resource limits, N+1
network/DB calls, manual O(n²) sorts, and more. Every finding says *why it
wastes energy* and what to do instead.

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

38 rules (GL001–GL038, see `--list-rules`) spanning Python, JS/TS/JSX/TSX,
Go, Rust, Java, Kotlin, Swift, C#, C/C++, PHP, Perl, Ruby, Bash, SQL, HTML,
CSS, Dockerfile, Terraform/OpenTofu, Kubernetes, and docker-compose/Swarm.
See [`docs/rules.md`](docs/rules.md) for the full reference — what each rule
detects, how it's triggered, and the remediation. Rule development is
deliberately open-ended — the rule set *is* the product. Proposals with an
energy rationale are the most valuable contribution.

## Status & roadmap

- [x] AST-based rules for Python (GL001, GL018, GL023, GL030, GL031)
- [ ] Broader AST-based rules beyond Python (regex has false-positive limits
      for JS/Go/Rust/etc.)
- [ ] C#, Ruby, Kotlin, Swift coverage is currently a single high-confidence
      rule each — room to grow

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
