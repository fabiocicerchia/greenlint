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
- **Reporters** — human-readable (default), JSON (`--format json`), and GitHub
  workflow annotations (`--format github`).
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

Parsing once was only half of it: each rule then called `ast.walk(tree)` to
find the handful of node types it cared about, so a scan walked every tree six
or seven times over. Profiling put ~65% of a whole run inside
`ast.iter_child_nodes`. `index_python()` now makes one breadth-first pass and
collects what every rule needs — the loops, tries, functions and classes, each
paired with the loops enclosing it, plus which scopes own a loop at all. Two
consequences beyond the obvious one: "is this statement inside a loop?" is a
lookup rather than a walk of every loop's subtree (which was quadratic in
nesting depth), and GL007 skips a scope with no loop in it without walking it
to find out — which is most functions. Breadth-first because that is
`ast.walk`'s order, so each rule still sees its nodes in the order it did
before.

`_blank_comments()` is the other half of a scan's cost, and the only part
whose work is per character rather than per match. It now jumps between the
characters that can change anything — a quote, a comment token, a block opener
— with `re` doing the skipping in C, and records spans to blank rather than
editing a per-character copy of the file (`list(text)` is eight bytes of list
for every byte of source, allocated for every file scanned). A file with no
comment token in it returns immediately.

Together these are ~2.8x on real Python with byte-identical findings; the
rewrite was checked against the previous implementation over ~158,000
generated (text, language) pairs plus every file in the standard library.

Cross-language rules (e.g. GL002 sub-100ms polling, GL005 `SELECT *`) use one
compiled regex with a `|`-separated alternative per language's idiom (Python
`time.sleep()`, Go `time.Sleep()`, Rust `thread::sleep()`, bash `sleep`, PHP/
Perl/C/C++ `usleep()`, Kotlin `delay()`, Swift `Timer.scheduledTimer`, etc.),
gated by the same `langs` set every other rule uses — cheaper than a rule per
language, at the cost of a longer pattern. `GL005` (`SELECT * FROM`) needs no
per-language alternatives at all since it's matching an embedded SQL string
literal, whose text looks the same regardless of the host language.

## Editor integration

`editors/vscode/` holds a VS Code extension. It runs the same `RULES` table
rather than reimplementing anything: there is one rule set, and a rule added to
`greenlint.py` appears in the editor with no change on the other side.

Three small pieces of the module exist for it, and only for it:

- **`scan_file(path, disabled, text=None)`** — the `text` override scans a
  buffer that has not been saved. Without it an editor has to write a temp file
  per keystroke to get a finding, which is a lot of disk churn for a tool about
  not wasting energy. `path` still decides the language, so it must be the name
  the buffer will be saved under.
- **`iter_files(paths, config)`** — the walk and the ignore-glob match, split out
  of `scan()`. The extension caches per file so it needs to drive the walk
  itself; two copies of this logic would drift, and a file the CLI ignores
  still being flagged in the editor is the kind of disagreement nobody debugs.
- **`scannable(path)`** and **`finding_sort_key(finding)`** — "would any rule
  even look at this file?", derived from `RULES` rather than a hardcoded list,
  and the CLI's ordering, so a front end assembling its own list produces the
  same order. `scan_file()` on a file no rule targets yields nothing either way;
  the predicate just lets a caller skip the read. The CLI does not use it —
  reading a PNG and matching nothing is wasted I/O, but changing what the CLI
  touches is a bigger decision than making a background scan cheap.

`editors/vscode/server/greenlint_server.py` is a long-lived process speaking
newline-delimited JSON over stdio. It exists because a CLI run spends ~100 ms on
interpreter startup and regex compilation before reading a byte — per save that
is tolerable, per keystroke it is the whole cost — and because a cache is only
worth having if it outlives the request. Results are held against both a
`(mtime, size)` stamp and a content hash, so an unchanged file is answered
without being opened and a rewritten-but-identical file is answered without
running a rule. A project scan services buffer scans between batches of files,
so a full walk never blocks what the developer is looking at.

A project scan streams: each progress event carries the findings made since the
last one, so the panel fills as the walk goes and the client can tell a slow
scan from a stuck one. The final message then carries the totals rather than
the findings again — they have already crossed the pipe once. Those totals are
counts per severity, per rule and per file, and deliberately not a single
score: the CO2e hints describe different physical quantities, so summing them
would produce a number with no unit.

Record further significant choices here (or in a `docs/adr/` folder if they
pile up).
