"""Deciding which files are worth reading at all."""

from __future__ import annotations

import fnmatch
import functools
import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePath

from .base import Config, Finding, Matcher
from .baselines import finding_sort_key
from .scanning import scan_file

# -------------------------------------------------------- file discovery ---


@functools.lru_cache(maxsize=32)
def _ignore_matcher(patterns: tuple[str, ...]) -> Matcher | None:
    """One compiled regex for a whole ignore list.

    `fnmatch` per pattern per path meant a walk ran one regex match per glob per
    file — and once the editor merges in `files.exclude` and `search.exclude`
    that is a hundred of them, on every file, before anything is read. An
    alternation answers the same question in one. Cached on the patterns, of
    which there is one set per config.

    `normcase` is applied to the patterns here and to the path below, which is
    exactly what `fnmatch.fnmatch` does — and the whole of why it is slower than
    `fnmatchcase`. Dropping it would silently make ignore globs case-sensitive
    on Windows.
    """
    if not patterns:
        return None
    return re.compile("|".join(fnmatch.translate(os.path.normcase(p)) for p in patterns)).match


def _matches_any(rel: str, ignore: Sequence[str]) -> bool:
    """Match a posix path string against ignore globs.

    Tried both as given and with a leading `/`. `greenlint .` produces
    `tests/x.py`, which `*/tests/*` cannot match — so the obvious way to write
    an ignore glob silently did nothing, including in greenlint's own
    .greenlint.toml. Trying both keeps bare patterns like `tests/*` working too.
    """
    match = _ignore_matcher(tuple(ignore))
    if match is None:
        return False
    forms = (rel,) if rel.startswith("/") else (rel, "/" + rel)
    return any(match(os.path.normcase(form)) for form in forms)


def is_ignored(path: Path | str, config: Config | None = None) -> bool:
    """True if this path is under a pruned directory, or an `ignore` glob
    covers it.

    Its own function because a walk is not the only caller: the editor
    extension scans one open buffer at a time, and a file the CLI ignores must
    not sprout squiggles just because it was reached by being opened rather
    than by being walked to. The pruned-directory check is here for the same
    reason — the walk skips `.venv` wholesale, so a `.venv` file the editor
    asks about directly has to be skipped too, or the two disagree.
    """
    p = path if isinstance(path, PurePath) else Path(path)
    if not PRUNED_DIR_NAMES.isdisjoint(p.parts):
        return True
    ignore: list[str] = config["ignore"] if config else []
    if not ignore:
        return False
    return _matches_any(p.as_posix(), ignore)


def prunable_bases(ignore: Sequence[str]) -> list[str]:
    """The `<base>` of every ignore glob shaped `<base>/*`, which are the only
    ones a walk can act on before descending.

    `<base>/*` covers everything below `<base>`, because fnmatch's `*` crosses
    `/` — so a directory matching `<base>` can be skipped whole. Nothing else
    can: `*/vendor/*.py` covers only part of the directory, and `*/vendor`
    covers the directory entry itself but nothing inside it. Getting this wrong
    in the permissive direction would silently stop scanning files that are not
    ignored, so the test is on the shape of the pattern rather than on a guess
    about what it might match.
    """
    bases: list[str] = []
    for pattern in ignore:
        stripped = pattern.rstrip("*")
        if stripped != pattern and stripped.endswith("/") and len(stripped) > 1:
            bases.append(stripped[:-1])
    return bases


# Directories that are never worth walking into: version-control internals,
# installed dependencies and tool caches, none of which is code anyone here is
# writing. A virtualenv is the expensive one — a few thousand third-party .py
# files, each read and run past every rule, which is enough to make an editor
# scan look like a hang.
#
# `site-packages` is listed as well as the venv names because a venv can be
# called anything (`env3`, `.direnv`, a conda prefix); the directory the
# packages actually land in cannot. Build outputs (`dist`, `build`, `target`)
# are deliberately absent: those names belong to real source directories often
# enough that skipping them by default would hide findings. Use `ignore` in
# .greenlint.toml for those.
PRUNED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "site-packages",
        ".tox",
        ".nox",
        ".direnv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def walk_files(root: Path | str, prune_bases: Sequence[str] = ()) -> Iterator[Path]:
    """Yield every file under `root`, never descending into a pruned directory.

    `Path.rglob("*")` walks the whole tree and leaves the caller to filter, so
    `.git` and `node_modules` were listed in full and then thrown away — the two
    directories most likely to contain more files than the project does. This
    skips them at the directory, so they are never read.

    Symlinked directories are not followed and symlinked files are yielded,
    which is what `rglob` did.
    """
    # Paths are carried as strings and `scandir` hands back the joined form for
    # free, so a `Path` is only built for the files actually yielded — not for
    # every directory entry passed over on the way there.
    stack = [os.fspath(root) or "."]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in PRUNED_DIR_NAMES:
                            continue
                        if prune_bases and _matches_any(Path(entry.path).as_posix(), prune_bases):
                            continue
                        stack.append(entry.path)
                    elif entry.is_file():
                        yield Path(entry.path)
        except OSError:
            continue  # unreadable directory: nothing to scan and nothing to say


def iter_files(paths: Sequence[str], config: Config | None = None) -> Iterator[Path]:
    """Yield every file under `paths` that the config does not ignore.

    Split out of `scan()` so that other front ends — the editor extension in
    `extensions/vscode/`, which walks the tree itself to cache per file — select
    exactly the same files the CLI does. Two copies of this logic would drift,
    and a file the CLI ignores still being flagged in the editor is the kind of
    disagreement nobody debugs, they just stop trusting the tool.
    """
    config = config or {"disable": set(), "ignore": []}
    prune_bases = prunable_bases(config["ignore"])
    for root in paths:
        p = Path(root)
        files = iter([p]) if p.is_file() else walk_files(p, prune_bases)
        for f in files:
            if is_ignored(f, config):
                continue
            yield f


def scan(paths: Sequence[str], config: Config | None = None) -> list[Finding]:
    """Scan files/directories and return findings sorted by severity."""
    config = config or {"disable": set(), "ignore": []}
    findings: list[Finding] = []
    for f in iter_files(paths, config):
        findings.extend(scan_file(f, config["disable"]))
    findings.sort(key=finding_sort_key)
    return findings
