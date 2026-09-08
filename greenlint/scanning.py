"""Scanning one file, and a whole tree."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .astindex import PythonIndex, _parse_python, index_python
from .base import Finding
from .comments import _blank_comments, _blank_python_docstrings, _blank_strings
from .findings import _finding, _is_test_file, _LineIndex
from .infra import (
    _compose_resources_findings,
    _dockerfile_layer_bloat_findings,
    _fetch_depth_findings,
    _k8s_hpa_static_findings,
    _k8s_resources_findings,
    _tf_asg_static_size_findings,
    _tf_log_retention_findings,
    _tf_s3_lifecycle_findings,
)
from .pyrules import (
    _ast_bubble_sort_findings,
    _ast_busy_loop_findings,
    _ast_dict_iterator_findings,
    _ast_nested_loop_findings,
    _ast_quadratic_rebuild_findings,
    _ast_try_in_loop_findings,
)
from .rules import AST_RULE_IDS, PATTERN_RULES_BY_LANG, SCANNABLE_LANGS

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
