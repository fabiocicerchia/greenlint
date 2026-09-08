"""Ordering findings, and comparing a run against a baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import Finding, Rule

# ------------------------------------------------ ordering and baselines ---

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def finding_sort_key(finding: Finding) -> tuple[int, str, int]:
    """Sort key putting the findings worth fixing first. Named and exported so
    a front end that assembles its own list — the editor extension merging a
    freshly scanned buffer into a cached project scan — orders it the way the
    CLI would rather than inventing a second ordering.
    """
    return (SEVERITY_ORDER[finding["severity"]], finding["file"], finding["line"])


def applicable(rule: Rule, path: Path) -> bool:
    """Return True if the rule targets the file's language/extension."""
    if path.name == "Dockerfile" and "Dockerfile" in rule["langs"]:
        return True
    return path.suffix in rule["langs"]


def fingerprint(finding: Finding, root: Path | str) -> str:
    """Stable id for a finding, for the baseline to name it by.

    Line-insensitive, so it survives every edit above it — the same shape the
    sibling gandalf tool uses, for the same reason: a baseline keyed on line
    numbers is stale by the next commit.

    The path is stored relative to the baseline file, because the two callers
    disagree about paths otherwise: `greenlint .` in CI reports `src/db.py`
    and the editor reports `/home/you/proj/src/db.py`, and a baseline only
    earns its keep if both honour it.

    greenlint's messages are fixed per rule, so this is in practice one id per
    (file, rule): accepting `SELECT *` in `src/db.py` accepts every occurrence
    in that file, and a later one is accepted too. That is the cost of not
    keying on lines, and it is the right way round — a baseline exists to stop
    old findings nagging, not to be a precise inventory.
    """
    try:
        relative = Path(finding["file"]).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        relative = Path(finding["file"]).as_posix()
    key = f"{relative}|{finding['rule']}|{finding['message']}"
    return hashlib.sha1(key.encode("utf-8", "replace"), usedforsecurity=False).hexdigest()


def load_baseline(path: Path | str) -> set[str]:
    """Accepted fingerprints from a baseline file. Missing or unreadable is an
    empty baseline: a linter that stops reporting because a file it was not
    asked about is malformed would be worse than one that reports too much.
    """
    p = Path(path)
    if not p.is_file():
        return set()
    try:
        with p.open("rb") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    return set(data.get("fingerprints") or [])


def apply_baseline(findings: list[Finding], baseline: set[str], root: Path | str) -> list[Finding]:
    """Findings that the baseline does not already accept."""
    if not baseline:
        return findings
    return [f for f in findings if fingerprint(f, root) not in baseline]


def write_baseline(path: Path | str, findings: list[Finding], root: Path | str) -> int:
    """Snapshot every current finding so later runs stay quiet about them.
    Returns how many distinct ones were recorded."""
    fingerprints = sorted({fingerprint(f, root) for f in findings})
    Path(path).write_text(json.dumps({"version": 1, "fingerprints": fingerprints}, indent=2) + "\n")
    return len(fingerprints)
