# Changelog

## 0.1.0

First release.

- Findings as editor diagnostics on the offending line, with a hover carrying
  the rule id, what was found, *what to do instead*, and an order-of-magnitude
  CO2e figure. The rule id links to its section of the rules reference.
- Findings pane in the bottom panel as a native tree view: grouped by file, or
  by severity or rule from the toolbar; a distinct icon per severity; a count
  badge; expand-all and collapse-all; and a current-file / whole-project
  toggle.
- The greenlint HTML report in an editor tab, drawn from VS Code's own theme
  variables so it follows the editor's theme, contrast setting and font size.
- Findings stream into the pane as the walk proceeds rather than appearing all
  at once at the end; the totals are computed once over the finished set. A
  whole-tree scan is cancellable and reports progress twice a second.
- `.greenlint.toml` is honoured exactly as the CLI honours it — same walker,
  same ignore globs, same disable list — so what CI blocks on is what the
  editor shows.
- A baseline: **Write Baseline** accepts the findings a project has decided to
  live with, so an existing codebase starts green and only new findings nag.
  It writes `.greenlint-baseline.json`, which `greenlint` reads in CI too.
- VS Code's own `files.exclude` and `search.exclude` are taken as given: a
  directory they cover is skipped without being opened, rather than walked and
  then discarded.
- Scans are debounced rather than polled, cached against both a file's
  `(mtime, size)` and a hash of its contents, and run in one long-lived scan
  server per window instead of a process per scan. There is no periodic
  rescan: every change already arrives as an event.
