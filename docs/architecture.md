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
and dependency-free, at the cost of some false positives. AST-based rules are a
roadmap item for languages where the regex approach is too coarse. Record
further significant choices here (or in a `docs/adr/` folder if they pile up).
