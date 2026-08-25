# Contributing

Thanks for taking the time to contribute to greenlint!

## Getting started

1. Fork and clone the repo.
2. Install dev tooling and hooks: `make setup` then `make dev`
   (editable install with pytest, ruff, build; git hooks + pre-commit).
3. Create a branch: `git checkout -b feat/short-description`.

## Making changes

- Keep changes focused; one logical change per PR.
- Match the existing style; add or update tests.
- New rules need an energy rationale (the `suggestion` field explaining *why*
  it wastes energy and what to do instead) and a test.
- Update `docs/` and `examples/` when behavior changes.
- Make sure `make lint` and `make test` pass locally.
- If you touch the scan path, `make bench` prints what a scan costs before and
  after. `tests/test_performance.py` guards the cheap parts from growing back —
  it counts work (files opened, glob matches) rather than milliseconds, so it
  says the same thing on your laptop and on CI.

Don't edit `CHANGELOG.md` by hand — it's generated from commit messages by
release-please (see [Releases](#releases)).

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`,
`fix:`, `docs:`, `chore:`, etc. This keeps history readable and drives the
version bump: `fix:` → patch, `feat:` → minor, `feat!:` or a
`BREAKING CHANGE:` footer → major.

## Releases

Releases are automated by [release-please](.github/workflows/release.yml);
you don't tag or edit the changelog manually.

1. Merge `feat:`/`fix:` PRs into `main` as normal — **no tag is created**.
2. release-please keeps an open **release PR** ("chore: release X.Y.Z"),
   recalculating the next version (in `pyproject.toml`) and `CHANGELOG.md`.
3. When you're ready to ship, **merge the release PR** — that creates the
   `vX.Y.Z` tag and GitHub Release, which builds and (if enabled) publishes to
   PyPI.

## Pull requests

Fill out the PR template, link related issues, and request review. Be kind.

## License

By contributing you agree that your contributions are licensed under the
Apache License 2.0 (see `LICENSE`).
