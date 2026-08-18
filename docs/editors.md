# Editor integration

## VS Code

The extension in [`editors/vscode/`](https://github.com/fabiocicerchia/greenlint/tree/main/editors/vscode)
runs the same rule set as the CLI, while you type.

- squiggles on the offending line, with a hover explaining what was found, what
  to do instead, and roughly what it costs;
- a **Findings** panel at the bottom of the window, scoped to the current file
  or the whole project, filled by a project scan as it walks rather than after
  it finishes;
- an HTML report in a webview, drawn from VS Code's own theme variables — as is
  the rest of the UI, which is native throughout: diagnostics, tree view,
  Problems panel;
- the same `.greenlint.toml` the CLI reads — same walker, same ignore globs,
  same disable list, so what CI blocks on is what you see.

### Install

Install greenlint itself first; the extension drives it rather than
reimplementing it.

```sh
pipx install git+https://github.com/fabiocicerchia/greenlint
```

Then install the extension. It finds Python and greenlint on its own, falling
back to a `greenlint.py` in the workspace root — so a checkout of this
repository is linted by its own working copy.

Until it is published to the Marketplace, build it from the checkout:

```sh
make ext-install    # builds the .vsix and installs it into VS Code
```

`make ext-build` stops at the `.vsix` if you would rather install it from the
Extensions view (`...` → *Install from VSIX*). Reload the window afterwards.

### Keeping it cheap

Scanning on every keystroke would be a strange thing to ship with a tool about
not wasting energy, so it does not:

- **one warm process**, not one per scan — Python startup and the ~40 regex
  compiles happen once per session rather than once per keystroke;
- **debounced typing** — a burst of keystrokes resets a timer and costs one
  scan;
- **a two-layer cache** — an unchanged `(mtime, size)` is answered without
  opening the file, and a file rewritten with identical bytes is answered
  without running a rule, which is the common case after a branch switch;
- **no periodic scanning at all** — saves, external writes, creations,
  deletions and config edits all arrive as events, so a timer could only
  re-examine files nothing has touched;
- **files no rule targets are never opened**, with the extension set derived
  from the rule table itself;
- **the editor's own excludes are honoured** — whatever `files.exclude` and
  `search.exclude` hide is skipped, and a directory they cover is never opened
  rather than opened and discarded. `.greenlint.toml`'s `ignore` stays the
  shared setting that CI reads too; the editor excludes only narrow this
  window.

Set `greenlint.trace` and the output channel prints the mix behind every scan
(`312 files in 74 ms (8 scanned, 304 reused from cache, 41 skipped)`), so this
is checkable rather than a claim.

The extension's own
[README](https://github.com/fabiocicerchia/greenlint/blob/main/editors/vscode/README.md)
documents every setting and what to change on a very large repository.
