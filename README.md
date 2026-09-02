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

> **0.x — the rule set is the product, and it is still growing.** Rule IDs
> are stable once published; the set they belong to is not, so a minor
> release can add findings to a tree that was clean yesterday. Pin a version
> in CI, or record a baseline. Every hint is an order of magnitude, not a
> measurement — see [the arithmetic](#references).

```console
$ greenlint src/ .github/
.github/workflows/ci.yml:12: [GL003/high] cron job scheduled every minute
    ↳ every-minute CI/cron jobs rarely need it; widen the schedule
src/db.py:44: [GL005/medium] SELECT * query
    ↳ fetch only needed columns; less I/O, less network, less RAM

greenlint: 2 finding(s)
```

## How it works

One pass over the tree, no build, no execution:

```
  greenlint <paths...>
      │
  walk ────────────────────► .git and node_modules pruned before descending
      │                       ignore globs from .greenlint.toml + --exclude
      ▼  for each file
  blank comments ──────────► comment bodies become spaces, offsets preserved
      │                       so line numbers still point at the real file
      │                       (GL004 is the exception: it reads comments)
      │
  blank strings ───────────► same trick again, for the rules that describe code
      │                       shape rather than embedded content — `while(true)`
      │                       inside a doc string is prose, `SELECT *` inside
      │                       one is a query
      │
      ├─ .py  ─────────────► parse once, index once, then six AST rules
      │                       busy loop · quadratic rebuild · nested loop
      │                       bubble sort · dict iterator · try in loop
      ├─ .tf/.tofu ────────► resource-block rules
      ├─ .yml/.yaml ───────► CI fetch-depth · k8s limits · HPA · compose
      ├─ Dockerfile ───────► layer bloat
      └─ every language ───► the regex rules that apply to this extension
      │
      ▼
  baseline ────────────────► fingerprinted findings already accepted are dropped
      │
  sort ────────────────────► high, then medium, then low
      │
      ▼
  text | json | github
```

The AST rules exist because a regex cannot tell `while True:` with a `sleep`
from one without, and the regex rules exist because most of the file types
that waste the most energy — CI configs, Terraform, Kubernetes manifests —
have no parser worth carrying a dependency for. Blanking string literals is
how the regex rules buy back the largest class of false positive a parser
would have caught for free: a rule about code shape stops matching the example
in a docstring, a comment block quoted into a heredoc, or a test fixture.

More in [`docs/architecture.md`](docs/architecture.md).

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
greenlint . --exclude '*/dist/*'  # skip paths, on top of .greenlint.toml
greenlint . --write-baseline    # accept today's findings; only new ones nag
```

The whole interface:

```console
$ greenlint --help
usage: greenlint [-h] [--list-rules] [--format {text,json,github}]
                 [--fail-on-findings] [--config CONFIG] [--exclude GLOB]
                 [--baseline FILE] [--write-baseline [FILE]]
                 [paths ...]

positional arguments:
  paths                 files or directories to scan (default: the current
                        directory)

options:
  -h, --help            show this help message and exit
  --list-rules          print every rule with its energy rationale, then exit
  --format {text,json,github}
                        text for humans, json for tooling, github for workflow
                        annotations
  --fail-on-findings    exit 1 when anything is found; the CI gate
  --config CONFIG       path to config (default: ./.greenlint.toml if present)
  --exclude GLOB        skip paths matching this glob; repeatable, added to
                        `ignore` from the config
  --baseline FILE       accept the findings recorded in FILE (default:
                        ./.greenlint-baseline.json if present)
  --write-baseline [FILE]
                        record every current finding as accepted and exit
```

A real run, against the sample fixture (from inside it — this repo's own
`.greenlint.toml` ignores `*/examples/*`, or the fixtures would report
themselves back as findings):

```console
$ cd examples/basic && greenlint .
sample.py:5: [GL001/medium] busy loop without sleep
    ↳ poll with a backoff/sleep, or use an event-driven wait
    ~ ~150-200 gCO2e/day per instance (one core pegged continuously)
sample.py:10: [GL005/medium] SELECT * query
    ↳ fetch only needed columns; less I/O, less network, less RAM
    ~ ~15 gCO2e per GB of columns never read; negligible per call; ~1 gCO2e per 500 core-seconds of work removed

greenlint: 2 finding(s)
```

More in [`docs/getting-started.md`](docs/getting-started.md).

## Configuration

`.greenlint.toml` in the repository root, read from the working directory
unless `--config` says otherwise. Simple and not comprehensive — the full
reference is in [`docs/getting-started.md`](docs/getting-started.md):

```toml
# Rules this repo has decided not to act on.
disable = ["GL005"]

# Paths no rule should read. Matched against the path as given, so anchor
# them: "*/vendor/*", not "vendor".
ignore = [
  "*/vendor/*",
  "*/dist/*",
]
```

A malformed config aborts rather than degrading to "nothing disabled": a
config that looks applied and is not is worse than no config.

## In your editor

[`extensions/vscode/`](extensions/vscode/) is a VS Code extension running the same
rule set as you type: squiggles with a hover explaining what to do instead, a
Findings panel scoped to the file or the whole project, and an HTML report. It
drives `greenlint.py` itself through a warm scan server with a stat+hash cache,
so an unchanged file is never opened and an unchanged tree is never read.

```sh
code --install-extension fabiocicerchia.greenlint   # or search "greenlint" in the Extensions view
```

Also on [Open VSX](https://open-vsx.org/extension/fabiocicerchia/greenlint) for
VSCodium and Cursor. From a checkout instead, `make ext-install` builds the
`.vsix` and installs it.

More in [`docs/editors.md`](docs/editors.md).

## Documentation

Full docs live in [`docs/`](docs/) (also published via mkdocs). Runnable
examples live in [`examples/`](examples/).

## Common errors

**`greenlint: .greenlint.toml: \`disable\` must be a list, not a string — write \`disable = ["GL005"]\``** (exit 1)
The easy typo. `disable = "GL005"` is a five-character string, and iterating
it would disable nothing while looking applied, so it is refused instead.

**`greenlint: .greenlint.toml: invalid TOML — Invalid value (at end of document)`** (exit 1)
Same reasoning: a config that cannot be parsed stops the run rather than
silently becoming an empty one.

**`greenlint: no such baseline: .greenlint-baseline.json`** (exit 1)
Only when `--baseline` names the file explicitly. The default lookup is
allowed to miss — a repo without a baseline is the normal case — but a typed
path that does not exist is a mistake, not a no-op.

**`0 finding(s)` on a repo you expected findings in.**
Check the ignore globs: they are matched against the path as given, so
`vendor` matches nothing and `*/vendor/*` is what you meant. `.git` and
`node_modules` are pruned unconditionally, and test files opt out of the
long-lived-loop rules (GL001, GL002, GL007) by design.

## References

The gram figures are order-of-magnitude steers built from four published
numbers. Their derivations are in the header of `greenlint.py`; these are the
sources:

- [Ember, *Global Electricity Review 2024*](https://ember-energy.org/latest-insights/global-electricity-review-2024/electricity-transition-in-2023/)
  — 480 gCO2e/kWh, the world average power-sector intensity used throughout.
- [Aslan et al. 2018, *Electricity Intensity of Internet Data Transmission*](https://doi.org/10.1111/jiec.12630)
  — the halving-every-two-years trend behind the 0.03 kWh/GB figure.
- [Cloud Carbon Footprint methodology](https://www.cloudcarbonfootprint.org/docs/methodology/)
  — the per-vCPU watts and per-TBh storage coefficients.
- [Uptime Institute, *Global Data Center Survey 2024*](https://uptimeinstitute.com/resources/research-and-reports/uptime-institute-global-data-center-survey-results-2024)
  — the PUE range applied on top.

Everything downstream of those is arithmetic stated in a comment next to the
constant, so it can be checked rather than believed.

## Release cycle

[Semantic Versioning](https://semver.org/), cut by release-please from
[Conventional Commits](https://www.conventionalcommits.org/).

- **Major** — a change to the output contract: the JSON shape, the exit
  codes, or the meaning of a published rule ID.
- **Minor** — new rules. This is the one that matters: a minor release can
  find something in a tree that was clean before. Pin the version in CI, or
  take a baseline with `--write-baseline`.
- **Patch** — fixes to existing rules, including false positives.

A rule ID is never reused or re-pointed once published; a retired rule stays
retired.

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
