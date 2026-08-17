# greenlint for VS Code

[greenlint](https://github.com/fabiocicerchia/greenlint) flags **energy-wasteful
patterns** — busy loops, sub-100ms polling, every-minute crons, `SELECT *`,
full-history CI clones, full-fat base images, missing resource limits, N+1
queries, manual O(n²) sorts. This extension runs the same rule set, unmodified,
while you type.

Every rule the CLI knows, the editor knows: there is no second implementation
here. The extension drives `greenlint.py` itself through a small scan server, so
a rule added to the linter shows up in the editor with no change on this side.

## What you get

- **Squiggles** on the offending line, severity-mapped and configurable.
- **Hover tooltips** with the rule id, what was found, *what to do instead*, and
  an order-of-magnitude CO2e figure — the "why" is the point of the tool.
- **A Findings panel** at the bottom of the window, filtered to the current file
  or showing the whole project, groupable by severity, file or rule.
- **An HTML report**, in a webview or exported as a standalone file. Everything
  in the UI is native VS Code — diagnostics, the tree view, quick picks, the
  status bar — and the report is drawn from VS Code's own theme variables, so it
  follows your theme, contrast setting and font size. Exported, it falls back to
  a plain light/dark stylesheet so it still reads in a browser.
- **Quick fixes**: open the rule's reference, or disable the rule for the
  workspace by writing it into `.greenlint.toml`.
- **`.greenlint.toml` is honoured** exactly as the CLI honours it: same walker,
  same ignore globs, same disable list. What CI blocks on is what you see.

## Install

Not on the Marketplace yet, so build it from the checkout — from the repository
root:

```sh
make ext-install    # builds the .vsix and installs it into VS Code
```

`make ext-build` stops at the `.vsix` if you would rather install it from the
Extensions view (`...` → *Install from VSIX*). Reload the window afterwards.

## Requirements

Python 3.11+ and greenlint on the machine — any of:

```sh
pip install git+https://github.com/fabiocicerchia/greenlint
pipx install git+https://github.com/fabiocicerchia/greenlint
pip install -e .    # from a checkout: `make dev`, and rule edits are live
```

It looks for greenlint in this order, and logs the list it will try:

1. `greenlint.greenlintPath`, if you set it — the only candidate, because a
   typo there should be an error rather than a silent fallback to some other
   greenlint whose rules you never asked for;
2. a `greenlint.py` in a workspace root, so a checkout of the linter is linted
   by its own working copy;
3. `import greenlint` from `python3`, then `python` (`python` then `py` on
   Windows), then the interpreter that owns the `greenlint` command — read
   from its shebang — and pipx's venv. A pipx install is deliberately
   invisible to the `python3` on PATH, so looking only there would fail for
   exactly the people who followed the pipx instruction.

It needs a greenlint with the editor scan API (`iter_files`, `scannable`,
`is_ignored`, `scan_file(text=)`). An older release refuses to start and says
which names are missing, and the search moves on to the next candidate. The
check is on the names rather than a version number, so it stays honest without
anyone maintaining a floor.

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `greenlint.enable` | `true` | Master switch. |
| `greenlint.run` | `onType` | `onType`, `onSave` or `manual`. |
| `greenlint.debounceMs` | `400` | Idle time before an `onType` scan runs. |
| `greenlint.scanProjectOnStartup` | `true` | Populate the panel before you open a file. |
| `greenlint.projectScanIntervalMinutes` | `0` (off) | Periodic full rescan. See below — you probably do not want this. |
| `greenlint.maxFileBytes` | `1000000` | Skip files bigger than this. |
| `greenlint.cacheEntries` | `4096` | Files the scan server keeps results for. |
| `greenlint.severityLevels` | high→Warning, medium→Information, low→Hint | How severities become squiggles. |
| `greenlint.showCo2eEstimate` | `true` | Include the CO2e hint in hovers and the report. |
| `greenlint.trace` | `false` | Log every request, its timing and its cache outcome. |
| `greenlint.pythonPath`, `greenlint.greenlintPath` | auto | Override discovery. |

## How it stays cheap

A linter that re-reads your repository on every keystroke is a strange thing to
ship with a tool about not wasting energy. Five things keep it honest, and each
one is worth knowing about because each has a knob.

**One warm process, not one per scan.** A `greenlint` CLI run spends ~100 ms
starting Python, importing the module and compiling ~40 regexes before it reads
a byte. Per save that is tolerable; per keystroke it is the entire cost. The
extension starts one scan server for the window instead and keeps it warm, so
that work happens once per session. Restart it with **greenlint: Restart Scan
Server** if you change interpreters.

**Debounce, never poll.** Typing resets a timer; it does not queue a scan. A
burst of thirty keystrokes costs one scan, and the cost of each keystroke is a
`clearTimeout`. Raise `greenlint.debounceMs` on a slow machine or a large file —
800–1000 ms still feels immediate and roughly halves the scans in a fast typing
run. `onSave` is the cheapest setting that still keeps up with your work.

**A two-layer cache, so a rescan usually reads nothing.** Every file's findings
are stored against both its `(mtime, size)` and a hash of its contents:

- unchanged stat → the findings come back **without opening the file**;
- changed stat, same bytes → **one read, no rules run**. This is the common case
  after a branch switch, a `git stash pop`, or a formatter that reformatted
  nothing;
- genuinely changed → scanned, and only then.

A second project scan of an untouched tree therefore does one `stat` per file
and nothing else. Turn on `greenlint.trace` and the output channel prints the
mix for every scan — `312 files in 74 ms (8 scanned, 304 reused from cache, 41
skipped)` — so this is something you can check rather than take on trust.

**Files no rule targets are never opened.** The set of extensions comes from the
rule table itself, so it is exactly right and stays right as rules are added. In
a normal repository this drops most of the tree — images, lockfiles, binaries —
before any I/O. `greenlint.maxFileBytes` drops the vendored megabytes on top of
that, and `.greenlint.toml`'s `ignore` globs drop whatever you say they do.

**Bursts collapse.** A `git checkout` fires hundreds of file events. They are
batched for 1.5 s, and past 50 files the extension stops scanning them
individually and runs one project scan instead — which walks with the stat cache
and reads only what actually changed.

### On periodic scanning

`greenlint.projectScanIntervalMinutes` exists and defaults to **0, off**, which
is the recommendation. A timer's job would be to notice changes, and the
extension is already told about every one of them: saves, external writes,
creations, deletions and `.greenlint.toml` edits all arrive as events. A periodic
scan on top of that can only re-examine files nothing has touched — it wakes the
CPU, it defeats the disk's idle states, and its expected yield is zero findings.

Two cases where it earns its place, both about events that do not arrive:
a workspace on a network mount or a container bind-mount where file watching is
unreliable, and a tree written by something outside the editor (a code
generator, a sync client). If you are in one of those, 15–30 minutes is the
right order of magnitude. Anything under 5 minutes is a busy loop with extra
steps — which is, after all, `GL001`.

### Memory

The cache is a bounded LRU: `cacheEntries` files at roughly a kilobyte each, so
the 4096 default is a few megabytes and a repository ten times that size costs
nothing extra — the oldest entries fall out. Diagnostics for the whole project
live in VS Code, and those are proportional to findings, not files.

### If your repository is very large

In rough order of effect: add `ignore` globs to `.greenlint.toml` (they are
shared with CI, so this is worth doing anyway), turn off
`scanProjectOnStartup`, set `run` to `onSave`, and lower `maxFileBytes`.

The one to check first is what the workspace root actually is. A root one level
too high — a folder of projects rather than a project — turns a scan of a few
hundred files into a scan of a disk, and nothing in the editor makes that
obvious. The scan says how many files it walked, and warns once past 20,000.
The log line is the ground truth:

```
[greenlint] scanning /home/you/Projects
[greenlint] scanned /home/you/Projects: 31,402 files in 24,110 ms (…)
```

A project scan is never silent while it works, so a slow one and a stuck one
are distinguishable: progress arrives twice a second, and the timeout measures
silence rather than duration. Typing stays responsive throughout — buffer scans
are answered between batches of files, in milliseconds, while the walk
continues.

## Development

```sh
cd editors/vscode
npm install
npm run compile     # or: npm run watch
```

Then <kbd>F5</kbd> in VS Code to launch an Extension Development Host, which
loads the extension without installing it.

The scan server is `server/greenlint_server.py`; it speaks newline-delimited
JSON over stdio and is covered by the repository's pytest suite
(`tests/test_vscode_server.py`), so its caching behaviour is asserted rather
than assumed.

`npm run package` (what `make ext-build` calls) produces the `.vsix`. It copies
the repository's `LICENSE` in first, which is why that file is gitignored here.

## Licence

Apache 2.0, the same as greenlint.
