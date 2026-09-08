"""Blanking comments and strings, so a rule matches code and not prose."""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

from .astindex import PythonIndex

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
