# greenlint

[![CI](https://github.com/fabiocicerchia/greenlint/actions/workflows/ci.yml/badge.svg)](https://github.com/fabiocicerchia/greenlint/actions/workflows/ci.yml)
[![Security](https://github.com/fabiocicerchia/greenlint/actions/workflows/security.yml/badge.svg)](https://github.com/fabiocicerchia/greenlint/actions/workflows/security.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/fabiocicerchia/greenlint/badge)](https://securityscorecards.dev/viewer/?uri=github.com/fabiocicerchia/greenlint)
[![CI carbon](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/fabiocicerchia/greenlint/gh-pages/badge.json)](.github/workflows/carbon-badge.yml)
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
greenlint .                     # scan the current repo
greenlint --list-rules          # show every rule it knows
greenlint . --fail-on-findings  # exit non-zero if anything is found (CI gate)
greenlint . --format json       # machine-readable output
```

More in [`docs/getting-started.md`](docs/getting-started.md).

## In your editor

[`editors/vscode/`](editors/vscode/) is a VS Code extension running the same
rule set as you type: squiggles with a hover explaining what to do instead, a
Findings panel scoped to the file or the whole project, and an HTML report. It
drives `greenlint.py` itself through a warm scan server with a stat+hash cache,
so an unchanged file is never opened and an unchanged tree is never read — see
[`docs/editors.md`](docs/editors.md).

## Documentation

Full docs live in [`docs/`](docs/) (also published via mkdocs). Runnable
examples live in [`examples/`](examples/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). By participating you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md). greenlint uses
[Conventional Commits](https://www.conventionalcommits.org/) and release-please.

## Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) — please don't open a public issue.

## Support

Need help implementing this? [Get in touch](https://fabiocicerchia.it/contact).

## License

[Apache 2.0](LICENSE) © Fabio Cicerchia
