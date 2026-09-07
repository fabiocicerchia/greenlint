"""greenlint — static analysis for energy-wasteful patterns.

Rules are regex+context based and language-tagged; the rule set is the
product and grows over time. Every finding explains *why it wastes energy*
and what to do instead.

  greenlint src/
  greenlint --list-rules
  greenlint src/ --format json --fail-on-findings
  greenlint . --exclude '*/vendor/*' --exclude '*/dist/*'
"""

# Annotations are evaluated lazily: several helpers are typed against
# PythonIndex, which is defined further down beside the traversal it holds.
from __future__ import annotations

import argparse
import ast
import fnmatch
import functools
import hashlib
import json
import os
import re
import sys
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePath
from typing import Any

from .astindex import SCOPE_BOUNDARIES as SCOPE_BOUNDARIES
from .astindex import Collector as Collector
from .astindex import Loops as Loops
from .astindex import PythonIndex, _parse_python, index_python
from .base import BASELINE_FILENAME, CONFIG_FILENAME, Config, Finding, Matcher, Rule
from .carbon import BUSY_CORE_WATTS as BUSY_CORE_WATTS
from .carbon import CO2E_HINTS as CO2E_HINTS
from .carbon import G_CO2E_PER_GB as G_CO2E_PER_GB
from .carbon import GRID_INTENSITY_G_PER_KWH as GRID_INTENSITY_G_PER_KWH
from .carbon import KWH_PER_GB_TRANSFERRED as KWH_PER_GB_TRANSFERRED
from .carbon import PAIR as PAIR
from .carbon import core_seconds_per_gram as core_seconds_per_gram
from .findings import TEST_FILENAME as TEST_FILENAME
from .findings import _finding, _is_test_file, _LineIndex
from .pyrules import NUMERIC_ONLY_OPS as NUMERIC_ONLY_OPS
from .pyrules import PROBE_CALLS as PROBE_CALLS
from .pyrules import SCALAR_CALLS as SCALAR_CALLS
from .pyrules import SCALAR_OPS as SCALAR_OPS
from .pyrules import (
    _ast_bubble_sort_findings,
    _ast_busy_loop_findings,
    _ast_dict_iterator_findings,
    _ast_nested_loop_findings,
    _ast_quadratic_rebuild_findings,
    _ast_try_in_loop_findings,
)
from .rules import AST_RULE_IDS, PATTERN_RULES_BY_LANG, RULES, RULES_BY_ID, SCANNABLE_LANGS

# --------------------------------------------------------- configuration ---


def _as_list(value: Any, key: str) -> list[str]:
    """Coerce a config value to a list of strings, refusing a bare string.

    `disable = "GL005"` is the easy typo, and `set("GL005")` is the set of five
    characters — a config that looks applied and disables nothing. TOML gives
    us the real type, so the mistake is worth naming rather than silently
    iterating.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raise SystemExit(
            f'greenlint: {CONFIG_FILENAME}: `{key}` must be a list, not a string — write `{key} = ["{value}"]`'
        )
    return [str(v) for v in value]


def load_config(path: str | None = None) -> Config:
    """Load `.greenlint.toml` (rule disable list + ignore globs). Missing
    file → no-op config. `path` overrides the default cwd lookup.

    A malformed config aborts rather than degrading to "no rules disabled":
    silently ignoring the file is how a config that looks applied turns out
    not to be.
    """
    cfg_path = Path(path) if path else Path.cwd() / CONFIG_FILENAME
    if not cfg_path.is_file():
        return {"disable": set(), "ignore": []}
    try:
        with cfg_path.open("rb") as fh:  # tomllib decodes UTF-8 itself, per spec
            data: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"greenlint: {cfg_path}: invalid TOML — {exc}") from exc
    return {
        "disable": set(_as_list(data.get("disable"), "disable")),
        "ignore": _as_list(data.get("ignore"), "ignore"),
    }


# ----------------------------------------------------- comment stripping ---

# Line- and block-comment syntax per extension. Dockerfile/unknown default to `#`.
_SLASH: tuple[str | None, tuple[str, str] | None] = ("//", ("/*", "*/"))
COMMENT_SYNTAX: dict[str, tuple[str | None, tuple[str, str] | None]] = {
    # CSS and HTML carry rules but had no entry at all. Both are listed with a
    # None line-comment form because neither language has one: `//` in CSS
    # would eat the rest of any line containing `url(http://…)`, which is a
    # worse bug than the gap it closes.
    ".css": (None, ("/*", "*/")),
    ".html": (None, ("<!--", "-->")),
    ".go": _SLASH,
    ".js": _SLASH,
    ".ts": _SLASH,
    ".jsx": _SLASH,
    ".tsx": _SLASH,
    ".c": _SLASH,
    ".h": _SLASH,
    ".cpp": _SLASH,
    ".cc": _SLASH,
    ".hpp": _SLASH,
    ".java": _SLASH,
    ".rs": _SLASH,
    ".kt": _SLASH,
    ".swift": _SLASH,
    ".cs": _SLASH,
    ".php": _SLASH,
    ".scala": _SLASH,
    ".sql": ("--", ("/*", "*/")),
    ".py": ("#", None),
    ".sh": ("#", None),
    ".bash": ("#", None),
    ".rb": ("#", None),
    ".yml": ("#", None),
    ".yaml": ("#", None),
    ".tf": ("#", None),
    ".tofu": ("#", None),
    ".toml": ("#", None),
    ".pl": ("#", None),
    ".dockerfile": ("#", None),
}


# Everything but a newline, for blanking a span while keeping offsets and line
# numbers pointing at the real file.
_NOT_NEWLINE = re.compile(r"[^\n]")


def _blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each `(start, end)` span with spaces, newlines kept.

    Spliced from slices rather than edited character by character: the blanked
    regions are a small fraction of a file, and `re.sub` does the per-character
    part in C. Nothing to blank means the original string is handed straight
    back, with nothing allocated at all.
    """
    if not spans:
        return text
    pieces: list[str] = []
    prev = 0
    for start, end in spans:
        pieces.append(text[prev:start])
        pieces.append(_NOT_NEWLINE.sub(" ", text[start:end]))
        prev = end
    pieces.append(text[prev:])
    return "".join(pieces)


@functools.cache
def _comment_scanners(
    line_tok: str, block: tuple[str, str] | None
) -> tuple[re.Pattern[str], dict[str, re.Pattern[str]]]:
    """(outside-a-string, {quote: inside-that-string}) jump patterns.

    Outside a string the only characters that matter are a quote, a line
    comment token and a block opener — a newline resets nothing, since there is
    no open quote to reset. Inside one, only the closing quote, a backslash and
    a newline. Alternation order matters: the old loop tested quotes before
    comment tokens, and at a position that could be either, `re` takes the
    first alternative, so the order here keeps that precedence.

    Cached because there is one pattern per language, not one per file.
    """
    alternatives = ["[\"']", re.escape(line_tok)]
    if block:
        alternatives.append(re.escape(block[0]))
    outside = re.compile("|".join(alternatives))
    inside = {quote: re.compile(f"[\\n\\\\{quote}]") for quote in "\"'"}
    return outside, inside


def _step_in_string(text: str, i: int, quote: str, inside: dict[str, re.Pattern[str]]) -> tuple[int | None, str | None]:
    """Advance past the next character that can close the string open at `i`.

    Returns the offset to resume from and the quote still open — None once the
    string closed — or `(None, None)` when nothing can close it before EOF.
    """
    match = inside[quote].search(text, i)
    if match is None:
        return None, None
    i = match.start()
    ch = text[i]
    if ch == "\\":
        # A trailing backslash is a line continuation, not an escape of the
        # newline we use to resynchronise.
        if i + 1 < len(text) and text[i + 1] != "\n":
            i += 1
        return i + 1, quote
    # A newline resets the tracking; anything else here is the closing quote.
    return i + 1, None


def _is_apostrophe(text: str, i: int) -> bool:
    """True for the `'` in don't / it's / won't — a letter either side of it."""
    return 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha()


def _step_outside_string(
    text: str, i: int, outside: re.Pattern[str], line_tok: str, block: tuple[str, str] | None
) -> tuple[int | None, str | None, tuple[int, int] | None]:
    """Advance to the next string opener or comment at or after `i`.

    Returns the offset to resume from, the quote now open (None when the stop
    was a comment) and the comment's span to blank (None when it was a quote).
    `(None, None, None)` means nothing interesting is left in the file.
    """
    n = len(text)
    while True:
        match = outside.search(text, i)
        if match is None:
            return None, None, None
        i = match.start()
        ch = text[i]
        if ch in "\"'":
            if ch == "'" and _is_apostrophe(text, i):
                i += 1
                continue
            return i + 1, ch, None
        if text.startswith(line_tok, i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            return end, None, (i, end)
        if block is None:
            # Unreachable: with no block form the pattern offers only quotes
            # and the line token, both handled above. Stepping on rather than
            # indexing None keeps a future third token from crashing the scan.
            return i + 1, None, None
        end = text.find(block[1], i + len(block[0]))
        end = n if end == -1 else end + len(block[1])
        return end, None, (i, end)


def _blank_comments(text: str, path: Path) -> str:
    """Return `text` with comment bodies replaced by spaces.

    Length and every newline are preserved, so line numbers and match offsets
    computed against the result still point at the real file. Quoted strings
    are respected, so a `#` inside a SQL string is not mistaken for a comment.

    Without this, every regex rule fires on prose that *warns against* the
    pattern — `# never write SELECT * here` reported as a SELECT * query. That
    was six false positives out of six in a six-line probe.

    Quote tracking is reset at every newline, and a `'` between two letters is
    read as an apostrophe rather than an opening quote. `echo don't` otherwise
    opened a string that never closed, and *every comment in the rest of the
    file* stayed visible to the rules — reintroducing the false positives this
    function exists to remove, on any shell, YAML or Ruby file containing an
    ordinary English contraction.

    The cost is that a genuinely multi-line string containing a comment token
    gets blanked. That is a false negative, which is the safe direction: this
    whole pass exists because a linter that cries wolf gets switched off.
    """
    default: tuple[str | None, tuple[str, str] | None] = ("#", None) if path.name == "Dockerfile" else (None, None)
    line_tok, block = COMMENT_SYNTAX.get(path.suffix, default)
    if not line_tok:
        return text
    # Two C-speed substring searches before any character-at-a-time work: a
    # file with no comment token in it has nothing to blank, and in a scan of a
    # real tree that is a large share of the files. The loop below is the only
    # part of a scan whose cost is per character rather than per match.
    if line_tok not in text and not (block and block[0] in text):
        return text
    # Spans to blank, rather than a mutable copy of the file: `list(text)` is
    # one pointer per character — 8 bytes of list for every byte of source —
    # allocated for every file scanned, and thrown away by the join.
    # Jump between the characters that can change anything instead of visiting
    # every one. Source is overwhelmingly ordinary code: on the standard
    # library this loop ran once per character and was the single largest cost
    # in a scan. `re` does the skipping in C; the Python below still runs once
    # per interesting position, and the decisions it makes are unchanged.
    outside, inside = _comment_scanners(line_tok, block)
    spans: list[tuple[int, int]] = []
    i, n, quote = 0, len(text), None
    while i < n:
        if quote:
            i, quote = _step_in_string(text, i, quote, inside)
        else:
            i, quote, span = _step_outside_string(text, i, outside, line_tok, block)
            if span is not None:
                spans.append(span)
        if i is None:
            break
    return _blank_spans(text, spans)


# Languages whose string literals are worth blanking before a code-structure
# rule looks at them. Everything here uses C-style quoting; a language whose
# quoting rules differ enough to need its own scanner is better served by
# leaving its strings visible (a false negative) than by a scanner that
# desynchronises (false positives everywhere after the first mistake).
_STRING_LANGS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".mjs",
        ".cjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".swift",
        ".ts",
        ".tsx",
    }
)

# Opening a string, or the end of the line that resynchronises the scan.
_STRING_OPEN = re.compile(r"[\"'`\n]")


def _no_strings_to_blank(code: str, path: Path) -> bool:
    """True when this file cannot gain from blanking its strings.

    Either its language has no C-style quoting, or it holds no quote character
    at all — in a real tree that is a large share of the files. Same reasoning
    as the comment scanner's substring pre-check.
    """
    return path.suffix not in _STRING_LANGS or ('"' not in code and "'" not in code and "`" not in code)


def _string_end(code: str, i: int, quote: str) -> int:
    """Offset of the character that ends the literal whose body starts at `i`.

    A backslash escapes the next character; a newline ends the scan without
    closing the literal, which is what stops one mistake desynchronising the
    rest of the file.
    """
    n = len(code)
    while i < n:
        ch = code[i]
        if ch == "\\" and i + 1 < n and code[i + 1] != "\n":
            i += 2  # an escaped character, including \" and \'
            continue
        if ch in ("\n", quote):
            break
        i += 1
    return i


def _step_to_string_end(code: str, i: int) -> tuple[int | None, tuple[int, int] | None]:
    """Advance past the next string literal at or after `i`.

    Returns where to resume and the span to blank — `(None, None)` when nothing
    is left, and `(next_i, None)` for a character that opens no literal.
    """
    match = _STRING_OPEN.search(code, i)
    if match is None:
        return None, None
    i = match.start()
    quote = code[i]
    # A newline only resynchronises the scan, and an apostrophe between two
    # letters is a contraction rather than an opening quote — the same trap
    # `_blank_comments` documents. Getting either wrong opens a string that
    # never closes and blanks the rest of the line.
    if quote == "\n" or (quote == "'" and _is_apostrophe(code, i)):
        return i + 1, None
    end = _string_end(code, i + 1, quote)
    # Past the closing quote, or onto the newline that resynchronises us.
    resume = end + 1 if end < len(code) and code[end] == quote else end
    return resume, (i + 1, end) if end > i + 1 else None


def _blank_strings(code: str, path: Path) -> str:
    """Return `code` with string-literal bodies replaced by spaces.

    Offsets and newlines are preserved, exactly as `_blank_comments` preserves
    them, so line numbers still point at the real file.

    This is applied ONLY to rules marked `code_only` — those whose pattern
    describes the shape of the code rather than something embedded in it. The
    distinction is the whole point: `SELECT * FROM t` in a Go file is *always*
    inside a string literal and is a real query, while `sleep(0.01)` inside a
    string is documentation, a test fixture, or a code sample, and reporting it
    is the false positive this exists to remove.

    Quote state resets at every newline, like the comment scanner, so a
    multi-line string keeps its contents visible to the rules. That is a false
    negative, which is the safe direction — a linter that cries wolf gets
    switched off, and this whole pass exists because of that.
    """
    if _no_strings_to_blank(code, path):
        return code
    spans: list[tuple[int, int]] = []
    i, n = 0, len(code)
    while i < n:
        i, span = _step_to_string_end(code, i)
        if i is None:
            break
        if span is not None:
            spans.append(span)
    return _blank_spans(code, spans)


def _blank_python_docstrings(code: str, index: PythonIndex) -> str:
    """Blank module/class/function docstrings, preserving offsets.

    A docstring is prose, and prose about a pattern is not the pattern — the
    same reason comments are blanked. Ordinary string literals are left alone:
    `q = "SELECT * FROM t"` is a real query.

    Reads its docstring holders off the shared index rather than walking the
    tree for them, so a Python file is traversed once for this and every AST
    rule together.
    """
    holders: list[ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = [
        index.tree,
        *index.functions,
        *index.classes,
    ]
    spans: list[tuple[int, int]] = []
    starts: list[int] | None = None
    for node in holders:
        doc = node.body[0] if node.body else None
        if not (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str)):
            continue
        if starts is None:
            # Only built once a docstring is actually found: a file with none
            # (every generated or one-liner module in a tree) pays nothing.
            starts = []
            off = 0
            for line in code.splitlines(keepends=True):
                starts.append(off)
                off += len(line)
        start = starts[doc.lineno - 1] + doc.col_offset
        # `end_lineno`/`end_col_offset` are optional on the node type but always
        # set on anything `ast.parse` produced; falling back to the start blanks
        # nothing rather than running to the end of the file.
        end_lineno = doc.end_lineno if doc.end_lineno is not None else doc.lineno
        end_col = doc.end_col_offset if doc.end_col_offset is not None else doc.col_offset
        end = starts[end_lineno - 1] + end_col
        spans.append((start, min(end, len(code))))
    # Docstrings come off the index in traversal order, which is not file
    # order once functions nest; splicing needs them left to right.
    spans.sort()
    return _blank_spans(code, spans)


def _is_go_template(text: str) -> bool:
    """True for a Helm/Go-template YAML file. What such a file *renders to* is
    what matters, and greenlint does not render it — so manifest rules that ask
    "is key X present" cannot answer honestly here.
    """
    return "{{" in text and "}}" in text


# -------------------------------------------------- infrastructure rules ---


def _tf_resource_blocks(text: str, resource_type: str) -> Iterator[tuple[re.Match[str], str, int]]:
    """Yield (match, block_text, lineno) for every `resource "<resource_type>"
    "..." { ... }` in `text`. Block end is approximated as the next line that
    is just `}`, which matches typical `terraform fmt` output; not a real HCL
    parse, but enough to check whether a given argument is set inside it.
    Shared by every whole-resource-block Terraform check.
    """
    for m in re.finditer(rf'resource\s+"{resource_type}"\s+"[^"]+"\s*\{{', text):
        end = text.find("\n}", m.end())
        block = text[m.end() : end if end != -1 else len(text)]
        yield m, block, text.count("\n", 0, m.start()) + 1


def _tf_s3_lifecycle_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL013: an `aws_s3_bucket` resource block with no lifecycle rule anywhere
    inside it.
    """
    rule = RULES_BY_ID["GL013"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_s3_bucket"):
        if "lifecycle" not in block.lower():
            yield _finding(rule, path, lineno)


def _tf_asg_static_size_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL024: an `aws_autoscaling_group` whose min_size and max_size are the
    same literal value — a fixed-size group provisioned for peak load, not an
    elastic one.
    """
    rule = RULES_BY_ID["GL024"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_autoscaling_group"):
        min_m = re.search(r"min_size\s*=\s*(\d+)", block)
        max_m = re.search(r"max_size\s*=\s*(\d+)", block)
        if min_m and max_m and min_m.group(1) == max_m.group(1):
            yield _finding(rule, path, lineno)


def _tf_log_retention_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL026: an `aws_cloudwatch_log_group` with no `retention_in_days` set —
    logs are kept forever by default.
    """
    rule = RULES_BY_ID["GL026"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_cloudwatch_log_group"):
        if "retention_in_days" not in block:
            yield _finding(rule, path, lineno)


def _dockerfile_layer_bloat_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL029: more than one separate `RUN ... install` line in a Dockerfile —
    each is its own image layer. Flags every occurrence after the first.

    Counted per build stage, not per file: layers created in a stage that the
    final image does not inherit from are thrown away, so chaining installs
    across a `FROM ... AS build` boundary saves nothing and is usually
    impossible anyway.
    """
    rule = RULES_BY_ID["GL029"]
    stage_starts = [m.start() for m in re.finditer(r"^FROM\s+", text, re.MULTILINE)]
    installs = [
        m.start()
        for m in re.finditer(
            r"^RUN\s+.*\b(?:apt(?:-get)?|pip3?|npm|yum)\s+install\b",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
    ]
    seen_stages: set[int] = set()
    for pos in installs:
        stage = sum(1 for s in stage_starts if s < pos)
        if stage in seen_stages:
            yield _finding(rule, path, text.count("\n", 0, pos) + 1)
        seen_stages.add(stage)


def _k8s_resources_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL014: a Pod-spec-bearing manifest with no `resources:` block anywhere
    in the file. File-wide, not per-container; a real gap for single-manifest
    repos, a false negative for values shared via Helm/Kustomize overlays.

    Go-template files are skipped: in a Helm chart the pod spec usually lives
    in an included partial and `resources:` comes from `values.yaml`, so the
    unrendered template says nothing about whether the workload is bounded.
    """
    rule = RULES_BY_ID["GL014"]
    if _is_go_template(text):
        return
    m = re.search(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Pod)\s*$", text, re.MULTILINE)
    if m and "resources:" not in text:
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


def _k8s_hpa_static_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL033: a `HorizontalPodAutoscaler` manifest whose minReplicas and
    maxReplicas are the same literal value — a fixed-range HPA, not an
    elastic one.
    """
    rule = RULES_BY_ID["GL033"]
    if not re.search(r"^kind:\s*HorizontalPodAutoscaler\s*$", text, re.MULTILINE):
        return
    min_m = re.search(r"minReplicas:\s*(\d+)", text)
    max_m = re.search(r"maxReplicas:\s*(\d+)", text)
    if min_m and max_m and min_m.group(1) == max_m.group(1):
        yield _finding(rule, path, text.count("\n", 0, min_m.start()) + 1)


# Tools that read commit history, not just the working tree: a shallow clone
# makes them wrong (or makes them fail), so `fetch-depth: 0` is the correct
# setting and GL004 must not nag about it. Matched case-insensitively against
# the whole workflow file.
NEEDS_FULL_HISTORY = re.compile(
    r"gitleaks|trufflehog|sonar|codecov|scorecard|release-please|semantic-release"
    r"|git-cliff|gitversion|conventional-changelog|git\s+log|git\s+describe"
    # goreleaser builds its changelog from the tag history.
    r"|goreleaser"
    # Reviewers that diff a PR against its merge-base need both branches.
    # super-linter belongs here too: with VALIDATE_ALL_CODEBASE off it lints
    # the diff against the default branch, which it cannot compute from a
    # shallow clone.
    r"|gandalf|merge-base|super-linter"
    # Docs builds that stamp a "last updated" date per page read each file's
    # own commit history — mkdocs-material's git-revision-date-localized, and
    # the git-committers/git-authors plugins alongside it. A shallow clone
    # gives them nothing to read, so they fall back to the build date and
    # every page claims to have changed today.
    r"|git-revision-date|git-committers|git-authors",
    re.IGNORECASE,
)


def _job_starts(text: str, body_at: int) -> list[int]:
    """Offsets where each entry under `jobs:` begins, empty when unsegmentable."""
    body = text[body_at:]
    # The first key under `jobs:` sets the indent at which a sibling job starts.
    first = re.search(r"^([ \t]+)[\w-]+:[ \t]*$", body, re.MULTILINE)
    if not first:
        return []
    return [
        body_at + m.start() for m in re.finditer(rf"^{re.escape(first.group(1))}[\w-]+:[ \t]*$", body, re.MULTILINE)
    ]


def _bracketing(starts: list[int], pos: int, low: int, high: int) -> tuple[int, int]:
    """The two `starts` either side of `pos`, falling back to `low` and `high`."""
    before = [s for s in starts if s <= pos]
    after = [s for s in starts if s > pos]
    return (before[-1] if before else low), (after[0] if after else high)


def _job_span(text: str, pos: int) -> tuple[int, int]:
    """(start, end) of the `jobs:` entry containing `pos`, or the whole file.

    Crude on purpose — indentation, not a YAML parse, because greenlint has no
    YAML dependency and this only needs to find a block boundary. Any workflow
    it cannot segment falls back to the whole file, which is what the rule did
    everywhere before.
    """
    jobs = re.search(r"^jobs:[ \t]*$", text, re.MULTILINE)
    if not jobs or pos < jobs.end():
        return 0, len(text)
    starts = _job_starts(text, jobs.end())
    if not starts:
        return 0, len(text)
    return _bracketing(starts, pos, jobs.end(), len(text))


def _fetch_depth_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL004: a full-history clone in CI.

    Skipped when the **same job** runs something that genuinely needs the
    history — a secret scanner walking every commit, or a release tool deriving
    a version from tags. Telling those workflows to shallow-clone trades a
    working scan for a broken one, which is not a saving.

    Per job, not per file: one `gitleaks` job used to exempt every other job in
    the same workflow, including the ones cloning all of history for nothing.
    """
    rule = RULES_BY_ID["GL004"]
    for m in re.finditer(r"fetch-depth:\s*0", text):
        start, end = _job_span(text, m.start())
        if NEEDS_FULL_HISTORY.search(text, start, end):
            continue
        # A commented-out or discussed setting is not a setting. Prose about
        # `fetch-depth: 0` is common in the docs of tools that avoid needing it.
        line_start = text.rfind("\n", 0, m.start()) + 1
        if "#" in text[line_start : m.start()]:
            continue
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


def _compose_resources_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL034: a docker-compose/swarm file (`services:` top-level key) with no
    resource limit anywhere in the file — neither the Swarm-mode
    `deploy.resources` block nor the classic `mem_limit`/`cpus` keys.
    """
    rule = RULES_BY_ID["GL034"]
    m = re.search(r"^services:\s*$", text, re.MULTILINE)
    if m and not re.search(r"mem_limit|nano_cpus|cpus\s*:|memory\s*:", text):
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


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


# -------------------------------------------------------------- scanning ---


def scannable(path: Path) -> bool:
    """True if any rule targets this file's language at all.

    Derived from `RULES` rather than a hardcoded extension list, so a rule for
    a new language brings its files into scope automatically. Every rule — the
    pattern ones, the AST ones and the per-format ones — is selected by suffix
    or by the name `Dockerfile`, so a file this returns False for cannot produce
    a finding whatever it contains. `scan_file` leans on that to return before
    reading it, and the editor extension before asking about it at all.

    A set lookup rather than a pass over `RULES`: this is asked once per file in
    a walk, and the answer only ever depended on the set of tags.
    """
    return path.suffix in SCANNABLE_LANGS or (path.name == "Dockerfile" and "Dockerfile" in SCANNABLE_LANGS)


# The AST rules, in the order their findings come out, wired to the ids
# `AST_RULE_IDS` names. Each takes the shared per-file index, never its own walk.
AST_FINDERS = (
    ("GL001", _ast_busy_loop_findings),
    ("GL007", _ast_quadratic_rebuild_findings),
    ("GL018", _ast_nested_loop_findings),
    ("GL023", _ast_bubble_sort_findings),
    ("GL030", _ast_dict_iterator_findings),
    ("GL031", _ast_try_in_loop_findings),
)

# The rules that need a whole resource block rather than one match, keyed the
# way `PATTERN_RULES_BY_LANG` is: the suffix, or `Dockerfile` by name. Tags that
# mean the same format share one tuple, the way the pattern index aliases them.
BLOCK_FINDERS = {
    ".tf": (
        ("GL013", _tf_s3_lifecycle_findings),
        ("GL024", _tf_asg_static_size_findings),
        ("GL026", _tf_log_retention_findings),
    ),
    ".yml": (
        ("GL014", _k8s_resources_findings),
        ("GL033", _k8s_hpa_static_findings),
        ("GL034", _compose_resources_findings),
    ),
    "Dockerfile": (("GL029", _dockerfile_layer_bloat_findings),),
}
BLOCK_FINDERS[".tofu"] = BLOCK_FINDERS[".tf"]
BLOCK_FINDERS[".yaml"] = BLOCK_FINDERS[".yml"]
BLOCK_FINDERS[".dockerfile"] = BLOCK_FINDERS["Dockerfile"]


def _lang_key(path: Path) -> str:
    """The tag the rule indexes are keyed by: the suffix, or `Dockerfile` by name."""
    return "Dockerfile" if path.name == "Dockerfile" else path.suffix


def _context_findings(
    path: Path, text: str, code: str, index: PythonIndex | None, disabled: frozenset[str]
) -> Iterator[Finding]:
    """Findings from the checks that read whole-file or whole-block context
    instead of matching one regex — the AST rules, and the per-format ones that
    look for the *absence* of a key.
    """
    if index is not None and not disabled >= AST_RULE_IDS:
        for rule_id, finder in AST_FINDERS:
            if rule_id not in disabled:
                yield from finder(path, index)
    # GL004 takes `text`, not `code`: it reads comments deliberately, to tell a
    # real `fetch-depth: 0` from one being discussed in a comment above it.
    if path.suffix in (".yml", ".yaml") and "GL004" not in disabled:
        yield from _fetch_depth_findings(path, text)
    for rule_id, finder in BLOCK_FINDERS.get(_lang_key(path), ()):
        if rule_id not in disabled:
            yield from finder(path, code)


def _pattern_findings(path: Path, code: str, disabled: frozenset[str]) -> Iterator[Finding]:
    """Findings from the single-regex rules tagged for this file's language,
    looked up rather than filtered — see `_pattern_rules_by_lang`.
    """
    line_of = _LineIndex(code).line_of
    # Built once, and only if some enabled rule for this language actually wants
    # it — blanking strings costs a pass over the file, and most languages have
    # no code_only rule at all.
    code_no_strings = None
    for rule in PATTERN_RULES_BY_LANG.get(_lang_key(path), ()):
        if rule["id"] in disabled:
            continue
        view = code
        if rule.get("code_only"):
            if code_no_strings is None:
                code_no_strings = _blank_strings(code, path)
            view = code_no_strings
        for m in rule["pattern"].finditer(view):
            yield _finding(rule, path, line_of(m.start()))


def scan_file(path: Path, disabled: frozenset[str] = frozenset(), text: str | None = None) -> Iterator[Finding]:
    """Yield findings for every enabled rule that matches the file's contents.

    `text` supplies the contents instead of reading them, for callers that
    already hold them — an editor scanning an unsaved buffer, say. `path` is
    still what picks the language, so it must be the name the buffer will be
    saved under. Without this an editor has to write a temp file per keystroke
    to get a scan, which is a lot of disk churn for a tool about not wasting
    energy.
    """
    # No rule targets this language, so there is nothing to find in it — and no
    # reason to read it. A checkout is full of images, lock files and minified
    # bundles that were being read in full and then matched against nothing.
    if not scannable(path):
        return
    if text is None:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return
    # Everything that pattern-matches works on this view, in which comment
    # bodies are spaces. Offsets and line numbers still line up with the file.
    # GL004 is the exception: it reads comments deliberately, to spot the tool
    # that needs the full history.
    code = _blank_comments(text, path)
    # Parsed once and reused: the docstring pass and the AST rules both need
    # this tree, and `ast.parse` on every Python file twice is exactly the kind
    # of waste this tool exists to point at.
    tree = _parse_python(path, text) if path.suffix == ".py" else None
    # Indexed once and shared, for the same reason the tree is parsed once: the
    # docstring pass and all six AST rules want the same handful of node types.
    index = index_python(tree) if tree is not None else None
    if index is not None:
        code = _blank_python_docstrings(code, index)
    # Rules about long-lived loops, applied to test code, only ever produce
    # noise: a test's tight wait is bounded by the test run and is the point.
    if _is_test_file(path):
        disabled = disabled | {"GL001", "GL002", "GL007"}
    yield from _context_findings(path, text, code, index, disabled)
    yield from _pattern_findings(path, code, disabled)


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


# ------------------------------------------------------------------- cli ---


def _build_parser() -> argparse.ArgumentParser:
    """The command-line surface: every flag greenlint accepts, and its help."""
    p = argparse.ArgumentParser(
        prog="greenlint",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="files or directories to scan (default: the current directory)",
    )
    p.add_argument(
        "--list-rules",
        action="store_true",
        help="print every rule with its energy rationale, then exit",
    )
    p.add_argument(
        "--format",
        choices=["text", "json", "github"],
        default="text",
        help="text for humans, json for tooling, github for workflow annotations",
    )
    p.add_argument("--fail-on-findings", action="store_true", help="exit 1 when anything is found; the CI gate")
    p.add_argument("--config", help=f"path to config (default: ./{CONFIG_FILENAME} if present)")
    p.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        # Same globs and same matching as `ignore` in the config, which is the
        # point: a caller that knows what to skip — an editor with its own
        # exclude list, a CI job scanning one subtree — should say so in the
        # vocabulary the project already uses, not a second one.
        help="skip paths matching this glob; repeatable, added to `ignore` from the config",
    )
    p.add_argument(
        "--baseline",
        metavar="FILE",
        help=f"accept the findings recorded in FILE (default: ./{BASELINE_FILENAME} if present)",
    )
    p.add_argument(
        "--write-baseline",
        nargs="?",
        const=BASELINE_FILENAME,
        metavar="FILE",
        help="record every current finding as accepted and exit",
    )
    return p


def _print_rules() -> None:
    """`--list-rules`: every rule, with the language tags it targets."""
    for r in RULES:
        print(f"{r['id']} [{r['severity']:6s}] ({', '.join(sorted(r['langs']))}): {r['message']}")  # noqa: T201 — the tool's output


def _print_github(findings: list[Finding]) -> None:
    """`--format github`: one workflow annotation per finding."""
    # https://docs.github.com/actions/using-workflows/workflow-commands-for-github-actions#setting-a-notice-message
    level = {"high": "error", "medium": "warning", "low": "notice"}
    for f in findings:
        print(  # noqa: T201 — the tool's output
            f"::{level[f['severity']]} file={f['file']},line={f['line']},"
            f"title=greenlint {f['rule']}::{f['message']} — {f['suggestion']}"
        )


def _print_text(findings: list[Finding], accepted: int, baseline_path: Path) -> None:
    """`--format text`: the human report, and the count a reader looks for."""
    for f in findings:
        print(f"{f['file']}:{f['line']}: [{f['rule']}/{f['severity']}] {f['message']}")  # noqa: T201 — the tool's output
        print(f"    ↳ {f['suggestion']}")  # noqa: T201 — the tool's output
        if f["co2e_estimate"]:
            print(f"    ~ {f['co2e_estimate']}")  # noqa: T201 — the tool's output
    accepted_note = f" ({accepted} accepted by {baseline_path})" if accepted else ""
    print(f"\ngreenlint: {len(findings)} finding(s){accepted_note}")  # noqa: T201 — the tool's output


def _resolve_baseline(explicit: str | None) -> Path:
    """The baseline file to honour, from `--baseline` or the default name.

    An explicit `--baseline` must exist; the default one is used when it happens
    to be there. A typo in a flag should be an error, not a silent no-op.
    """
    path = Path(explicit) if explicit else Path(BASELINE_FILENAME)
    if explicit and not path.is_file():
        raise SystemExit(f"greenlint: no such baseline: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if args.list_rules:
        _print_rules()
        return 0

    config = load_config(args.config)
    if args.exclude:
        config["ignore"] = [*config["ignore"], *args.exclude]
    findings = scan(args.paths or ["."], config)

    if args.write_baseline:
        path = Path(args.write_baseline)
        count = write_baseline(path, findings, path.parent)
        print(f"greenlint: {count} finding(s) accepted in {path}")  # noqa: T201 — the tool's output
        return 0

    baseline_path = _resolve_baseline(args.baseline)
    before = len(findings)
    findings = apply_baseline(findings, load_baseline(baseline_path), baseline_path.parent)
    if args.format == "json":
        json.dump(findings, sys.stdout, indent=2)
    elif args.format == "github":
        _print_github(findings)
    else:
        _print_text(findings, before - len(findings), baseline_path)
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    sys.exit(main())
