# TODO

Open items only. Completed work is dropped from here — the CHANGELOG
is the record of what shipped.

- [ ] Broader AST-based rules beyond Python (regex has false-positive limits
      for JS/Go/Rust/etc.)
- [ ] C#, Ruby, Kotlin, Swift coverage is currently a single high-confidence
      rule each — room to grow
- [ ] Publish the VS Code extension (`extensions/vscode/`) to the Marketplace and
      to Open VSX; until then it is build-from-checkout only
- [ ] The extension's TypeScript is compiled in CI but not tested — the scan
      server it drives is covered by pytest, the editor glue is not
- [ ] `scannable()` could gate the CLI's walk too, so `greenlint .` stops
      reading files no rule targets. Same findings, less I/O — but it changes
      what the CLI touches, so it wants a deliberate decision
