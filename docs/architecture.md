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

A `RULES` entry may set `pattern: None` when the check needs whole-file or
whole-resource-block context a single regex match can't express — mostly
rules that look for the *absence* of a keyword (GL013/GL014/GL024/GL026/
GL029/GL033/GL034). These are wired into `scan_file` as small generator
functions, same shape as the GL001 AST check, rather than growing the regex
engine to do double duty. `_tf_resource_blocks()` factors out the shared
"find this Terraform resource type's block and hand back its body text"
logic so GL013/GL024/GL026 don't each re-implement block extraction.

Python gained more AST-based rules alongside GL001 (GL018 same-collection
nested loops, GL023 manual swap-sort, GL030 dict-iterator, GL031
try/except-in-loop) since the stdlib `ast` module is free and more precise
than regex for anything shape-based. `_parse_python()` parses each `.py`
file's AST once per scan and hands the same tree to every AST rule, rather
than each rule re-parsing.

Cross-language rules (e.g. GL002 sub-100ms polling, GL005 `SELECT *`) use one
compiled regex with a `|`-separated alternative per language's idiom (Python
`time.sleep()`, Go `time.Sleep()`, Rust `thread::sleep()`, bash `sleep`, PHP/
Perl/C/C++ `usleep()`, Kotlin `delay()`, Swift `Timer.scheduledTimer`, etc.),
gated by the same `langs` set every other rule uses — cheaper than a rule per
language, at the cost of a longer pattern. `GL005` (`SELECT * FROM`) needs no
per-language alternatives at all since it's matching an embedded SQL string
literal, whose text looks the same regardless of the host language.

Record further significant choices here (or in a `docs/adr/` folder if they
pile up).
