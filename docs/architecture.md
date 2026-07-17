# Architecture

greenlint is a single module (`greenlint.py`) with no runtime dependencies.

## Overview

A scan walks the target paths, matches each file's extension against the
language tags on every rule, and runs the rule's compiled regex over the file
contents. Each match becomes a finding carrying its rule id, severity,
message, and energy-saving suggestion.

## Components

- **`RULES`** — the rule table: `id`, `langs`, `severity`, compiled `pattern`,
  `message`, `suggestion`. This list *is* the product; it grows over time.
- **Scanner** — walks paths, filters files by extension, applies matching
  rules, collects findings.
- **Reporters** — human-readable (default) and JSON (`--format json`).
- **CLI** (`main`) — argument parsing, `--list-rules`, `--fail-on-findings`.

## Data flow

```
paths → walk files → filter by extension → match rules → findings → report
```

## Decisions

Rules are regex + context based rather than AST based: cheap, language-agnostic,
and dependency-free, at the cost of some false positives. GL001 (Python busy
loop) is the first exception — it uses the stdlib `ast` module to check for a
real `sleep()` call reachable from inside the loop body, instead of a
"does the word sleep appear anywhere in the file" regex. JS has no stdlib
parser, so an AST-based JS rule would need a new runtime dependency, which
conflicts with the dependency-free guardrail — still regex for now.

A `RULES` entry may set `pattern: None` when the check needs whole-file
context a single regex match can't express (e.g. GL013/GL014 look for the
*absence* of a keyword inside a resource block or file). These are wired into
`scan_file` as small generator functions, same shape as the GL001 AST check,
rather than growing the regex engine to do double duty. Record further
significant choices here (or in a `docs/adr/` folder if they pile up).
