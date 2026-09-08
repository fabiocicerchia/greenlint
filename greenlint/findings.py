"""Building a finding, and deciding whether a path is test code."""

from __future__ import annotations

import bisect
import re
from pathlib import Path

from .base import Finding, Rule
from .carbon import CO2E_HINTS

# -------------------------------------------------------------- findings ---

# `foo_test.go`, `test_foo.py`, `foo.test.ts`, `foo.spec.ts`.
TEST_FILENAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|_spec\.)", re.IGNORECASE)


def _is_test_file(path: Path) -> bool:
    """True for test code. Tight sleeps and busy waits in a test are bounded by
    the test run and are usually the point (waiting for a condition quickly),
    so the energy rules that target long-lived loops do not apply.

    Matched on the filename plus an exact `test`/`tests`/`spec` directory
    component — not a substring of the whole path, which would exempt every
    file in a checkout that happens to sit under a directory containing "test".
    """
    if TEST_FILENAME.search(path.name):
        return True
    return any(part.lower() in ("test", "tests", "spec", "specs") for part in path.parts[:-1])


class _LineIndex:
    """`line_of(offset)` -> 1-based line number, over an index built at most once.

    `text.count("\\n", 0, offset)` per match rescans the file from the top, so a
    file the same rule matches a thousand times was read a thousand times over —
    quadratic, and the files that hit it (generated SQL, bundled JS) are exactly
    the large ones. The index is built on the first call, so the overwhelming
    majority of files, which match nothing, pay nothing for it.
    """

    __slots__ = ("_starts", "_text")

    def __init__(self, text: str) -> None:
        self._text = text
        self._starts: list[int] | None = None

    def line_of(self, offset: int) -> int:
        if self._starts is None:
            starts: list[int] = []
            pos = self._text.find("\n")
            while pos != -1:
                starts.append(pos)
                pos = self._text.find("\n", pos + 1)
            self._starts = starts
        # bisect_left: newlines strictly before the offset, which is what
        # `count` reported for a match starting on the newline itself.
        return bisect.bisect_left(self._starts, offset) + 1


def _finding(rule: Rule, path: Path, line: int) -> Finding:
    """Build one finding from the rule that fired.

    Every field a consumer sees is assembled here — the JSON output, the
    editor extension and the baseline fingerprint all read this shape, so a
    rule can never emit a finding that is missing its *why* or its
    suggestion.
    """
    return {
        "rule": rule["id"],
        "severity": rule["severity"],
        "file": str(path),
        "line": line,
        "message": rule["message"],
        "suggestion": rule["suggestion"],
        "co2e_estimate": CO2E_HINTS.get(rule["id"], ""),
    }
