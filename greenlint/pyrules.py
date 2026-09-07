"""The rules that need a Python AST rather than a regex."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

from .astindex import PythonIndex, _loop_can_exit, _walk_own_loops
from .base import Finding
from .carbon import PAIR
from .findings import _finding
from .rules import RULES_BY_ID

# ------------------------------------------------------ python AST rules ---


def _calls_sleep(node: ast.AST) -> bool:
    """True when `node` is a call to something named `sleep` — `time.sleep(x)`,
    `asyncio.sleep(x)` or a bare `sleep(x)` pulled in by `from time import`.
    """
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Attribute) and node.func.attr == "sleep")
        or (isinstance(node.func, ast.Name) and node.func.id == "sleep")
    )


def _ast_busy_loop_findings(path: Path, index: PythonIndex) -> Iterator[Finding]:
    """AST-based replacement for GL001 on Python: the regex version flags
    `while True:` unless "sleep" appears *anywhere* in the file, which both
    misses loops whose sleep is in an unrelated function and flags loops that
    do sleep but happen to share a file with the word "sleep" elsewhere.
    Walking the loop body directly for a real sleep call fixes both.
    """
    rule = RULES_BY_ID["GL001"]
    for node, _ in index.whiles:
        if not (isinstance(node.test, ast.Constant) and node.test.value is True):
            continue
        sleeps = any(_calls_sleep(n) for body_node in node.body for n in ast.walk(body_node))
        if sleeps or _loop_can_exit(node):
            continue
        yield _finding(rule, path, node.lineno)


def _ast_nested_loop_findings(path: Path, index: PythonIndex) -> Iterator[Finding]:
    """GL018: an inner `for` loop iterating over the same named collection as
    an enclosing `for` loop — a manual all-pairs O(n^2) scan (e.g. checking
    every element against every other). Only matches when both loops iterate
    a plain variable name, so `range(n)`/`enumerate(...)` nested loops (often
    legitimate matrix/grid code, not a same-collection rescan) are left alone.
    `seen` dedupes an inner loop matched from more than one enclosing loop
    when loops are nested three or more deep.
    """
    rule = RULES_BY_ID["GL018"]
    seen: set[int] = set()
    for node, enclosing in index.fors:
        if not isinstance(node.iter, ast.Name) or node.lineno in seen:
            continue
        if any(
            type(outer) is ast.For and isinstance(outer.iter, ast.Name) and outer.iter.id == node.iter.id
            for outer in enclosing
        ):
            seen.add(node.lineno)
            yield _finding(rule, path, node.lineno)


def _is_tuple_swap(stmt: ast.AST) -> bool:
    """True for the idiomatic Python swap `a[i], a[j] = a[j], a[i]` — two
    subscripts assigned from two subscripts. That shape only shows up when
    someone is hand-rolling an in-place swap, i.e. a manual sort.
    """
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Tuple)
        and len(stmt.targets[0].elts) == PAIR
        and all(isinstance(e, ast.Subscript) for e in stmt.targets[0].elts)
        and isinstance(stmt.value, ast.Tuple)
        and len(stmt.value.elts) == PAIR
        and all(isinstance(e, ast.Subscript) for e in stmt.value.elts)
    )


def _ast_bubble_sort_findings(path: Path, index: PythonIndex) -> Iterator[Finding]:
    """GL023: a `for` loop nested inside another `for` loop whose body
    contains an element swap — the textbook shape of a hand-rolled bubble or
    selection sort.
    """
    rule = RULES_BY_ID["GL023"]
    seen: set[int] = set()
    for node, enclosing in index.fors:
        if node.lineno in seen or not any(type(outer) is ast.For for outer in enclosing):
            continue
        if any(_is_tuple_swap(stmt) for stmt in ast.walk(node)):
            seen.add(node.lineno)
            yield _finding(rule, path, node.lineno)


def _ast_dict_iterator_findings(path: Path, index: PythonIndex) -> Iterator[Finding]:
    """GL030: `for k, v in d.items()` where the key or the value is discarded
    (bound to `_`) — the discarded half didn't need building/unpacking at all.
    """
    rule = RULES_BY_ID["GL030"]
    for node, _ in index.fors:
        if not (isinstance(node.target, ast.Tuple) and len(node.target.elts) == PAIR):
            continue
        if not (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr == "items"
        ):
            continue
        key, value = node.target.elts
        if any(isinstance(e, ast.Name) and e.id == "_" for e in (key, value)):
            yield _finding(rule, path, node.lineno)


# Builtins/constructors whose result is a number or a duration, never a
# sequence — `n += len(x)` is a counter, not a rebuild.
SCALAR_CALLS = frozenset({"len", "sum", "int", "float", "round", "abs", "ord", "timedelta", "Decimal"})
# Operators that only numbers support, so an expression using one is numeric.
SCALAR_OPS = (ast.Div, ast.FloorDiv, ast.Sub, ast.Mod, ast.Pow)

# Operators no sequence defines, so a name appearing as an operand of one is
# certainly a number. `+` and `*` are shared with str/bytes/tuple/list, and `%`
# is str formatting, so none of those three prove anything and none are here.
NUMERIC_ONLY_OPS = (ast.Sub, ast.Div, ast.FloorDiv, ast.Pow, ast.MatMult)


def _note_numeric(numeric: set[str], node: ast.AST) -> None:
    """Record `node`'s name in `numeric`, when `node` is a plain name."""
    if isinstance(node, ast.Name):
        numeric.add(node.id)


def _scalar_assign_targets(node: ast.Assign | ast.AnnAssign) -> tuple[ast.expr, ...]:
    """The targets of an assignment whose value is certainly numeric.

    A name *assigned* arithmetic is as numeric as one used in it, and this is
    the commoner shape: `day = start - (start % DAY)` then `day += DAY` in the
    loop. Reading only operands left the target of the seed unclassified,
    because it never appears beside an operator itself.
    """
    if not _is_scalar_expr(node.value):
        return ()
    return tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)


def _numeric_operands(node: ast.AST) -> tuple[ast.expr, ...]:
    """The sub-expressions this node proves are numeric, or `()` for none."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, NUMERIC_ONLY_OPS):
        return (node.left, node.right)
    if isinstance(node, ast.AugAssign) and isinstance(node.op, NUMERIC_ONLY_OPS):
        return (node.target,)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return (node.operand,)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return _scalar_assign_targets(node)
    return ()


def _names_used_as_numbers(nodes: Iterable[ast.AST]) -> set[str]:
    """Names that arithmetic elsewhere in this scope proves are numeric.

    `_names_bound_to_lists` can only classify a name it watched being
    initialised to a literal, and a counter seeded from something opaque — a
    parameter, a call, another name — tells it nothing. `y = top` then
    `y += row_height(r) + gap` inside a loop therefore read as a sequence
    rebuild, which is how this rule fired on the layout arithmetic of an SVG
    renderer.

    A scope that walks a coordinate almost always does arithmetic on it that
    only numbers support, and one `y - gap` or `-y` settles the question. This
    infers nothing the operators do not already guarantee: `s - 1` on the str
    that GL007 exists to catch is a TypeError, so no genuine rebuild is hidden.
    """
    numeric: set[str] = set()
    for node in nodes:
        for operand in _numeric_operands(node):
            _note_numeric(numeric, operand)
    return numeric


def _is_scalar_expr(node: ast.expr | None) -> bool:
    """True when the expression is certainly numeric, so `x += node` is a
    counter rather than a sequence rebuild. Conservative: unknown names are
    not scalar, because `data += chunk` is exactly the case worth catching.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float, complex)) and not isinstance(node.value, bool)
    if isinstance(node, ast.Call):
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        return name in SCALAR_CALLS
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, SCALAR_OPS):
            return True
        return _is_scalar_expr(node.left) or _is_scalar_expr(node.right)
    if isinstance(node, ast.UnaryOp):
        return _is_scalar_expr(node.operand)
    return False


def _classify_binding(target: ast.AST, value: ast.expr | None, lists: set[str], scalars: set[str]) -> None:
    """Record `target` in `lists` or `scalars`, judged from the shape of `value`."""
    # Unpacking binds each name to its own initialiser, so pair the sides
    # up rather than judging the tuple as a whole: `mwh, grams = 0.0, 0.0`
    # is two counters, and reading only single-name targets left both
    # unclassified — which flagged `mwh += r` as a rebuild.
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
        if len(target.elts) == len(value.elts):
            for element, initialiser in zip(target.elts, value.elts, strict=True):
                _classify_binding(element, initialiser, lists, scalars)
        return
    if not isinstance(target, ast.Name):
        return
    if isinstance(value, (ast.List, ast.ListComp)):
        lists.add(target.id)
    elif (
        isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and not isinstance(value.value, bool)
    ):
        scalars.add(target.id)


def _names_bound_to_lists(nodes: Iterable[ast.AST]) -> tuple[set[str], set[str]]:
    """(list_names, scalar_names) — names seen initialised to a list, and names
    seen initialised to a number, among `nodes`.

    `nodes` is one scope's own statements, never the whole module: `total = 0`
    in one function said nothing about `total` in the next, but sharing one
    namespace let any counter anywhere in the file silence a genuine rebuild
    everywhere else — and `total`, `out`, `result` and `s` collide constantly.

    `xs += <anything>` on a list is `list.extend`: in place, O(k). It is only
    quadratic when the target is immutable (str, bytes, tuple), because those
    build a whole new object each time. Knowing how the name was initialised is
    what tells the two apart — `lines = []` a few lines up is the difference
    between `lines += render(x)` being fine and being O(n^2), and `errors = 0`
    is the difference between `errors += e` being a counter and a rebuild.
    """
    lists: set[str] = set()
    scalars: set[str] = set()
    for node in nodes:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            _classify_binding(target, node.value, lists, scalars)
    return lists, scalars


def _accumulating_add(stmt: ast.stmt) -> tuple[ast.Name, ast.expr] | tuple[None, None]:
    """(target, value) when `stmt` accumulates onto a plain name with `+`/`+=`,
    else (None, None).

    Only `x += <expr>` and `x = x + <expr>`: `x = y + z` rebinds rather than
    accumulates, and a non-name target (`d[k] += …`) is not a name to track.
    """
    if isinstance(stmt, ast.AugAssign) and isinstance(stmt.op, ast.Add):
        target, value = stmt.target, stmt.value
    elif (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.value, ast.BinOp)
        and isinstance(stmt.value.op, ast.Add)
    ):
        target, value = stmt.targets[0], stmt.value
        left = stmt.value.left
        if not (isinstance(left, ast.Name) and left.id == getattr(target, "id", None)):
            return None, None
    else:
        return None, None
    return (target, value) if isinstance(target, ast.Name) else (None, None)


def _is_sequence_rebuild(stmt: ast.stmt, list_names: set[str], scalar_names: set[str]) -> bool:
    """True when `stmt` copies the whole sequence built so far — the O(n^2) shape."""
    target, value = _accumulating_add(stmt)
    if target is None:
        return False
    # A numeric counter (`total += 1`, `seen += len(chunk)`, `kwh +=
    # watts * hours / 1000`) accumulates in O(1) — not a rebuild.
    if _is_scalar_expr(value) or target.id in scalar_names:
        return False
    # `xs += ...` is `list.extend` when xs is a list: in place, O(k), no copy.
    # Either the list literal on the right proves it (`+=` a list is a
    # TypeError for str/bytes/tuple), or the name was seen being initialised to
    # one. Only the rebinding form (`xs = xs + [a]`) copies everything
    # accumulated so far.
    return not (
        isinstance(stmt, ast.AugAssign) and (isinstance(value, (ast.List, ast.ListComp)) or target.id in list_names)
    )


def _ast_quadratic_rebuild_findings(path: Path, index: PythonIndex) -> Iterator[Finding]:
    """GL007: accumulating with `+`/`+=` inside a loop, which copies the whole
    sequence built so far on every iteration — O(n^2) allocation where
    `list.append` / `''.join` are linear.

    Deliberately narrow: only `x += <expr>` and `x = x + <expr>` where the
    target is a plain name. `list.append()` in a loop is idiomatic and
    amortised O(1) — the previous version of this rule flagged it, which made
    the rule fire on almost every Python file that builds a list.
    """
    rule = RULES_BY_ID["GL007"]
    seen: set[int] = set()
    # One pass per scope, each judged against only its own name bindings.
    scopes = [index.tree, *index.functions]
    for scope in scopes:
        # A scope with no loop of its own cannot produce a finding here, and
        # most functions have none — so it is never walked at all.
        if scope not in index.loop_scopes:
            continue
        # One walk per scope, not one per scope plus one per loop in it: every
        # statement already knows which loops it sits inside.
        own = list(_walk_own_loops(scope))
        list_names, scalar_names = _names_bound_to_lists(node for node, _ in own)
        scalar_names |= _names_used_as_numbers(node for node, _ in own)
        for stmt, enclosing in own:
            if not enclosing:
                continue
            if not isinstance(stmt, (ast.AugAssign, ast.Assign)) or stmt.lineno in seen:
                continue
            if _is_sequence_rebuild(stmt, list_names, scalar_names):
                seen.add(stmt.lineno)
                yield _finding(rule, path, stmt.lineno)


# Conversions whose failure is routinely used as a type test, where a
# non-throwing check exists (`.isdigit()`, a regex, a guard).
PROBE_CALLS = frozenset({"int", "float", "complex", "Decimal"})


def _has_cheap_alternative(body: list[ast.stmt]) -> bool:
    """True when the guarded work is a lookup or a numeric conversion — the
    cases where the exception is standing in for a test that costs nothing:
    `d[k]` where `d.get(k)` works, `int(s)` where a guard works.

    Anything else (opening a file, parsing a document, a subprocess, a network
    call) can legitimately fail on good input, and catching it is the correct
    way to write that — not a pattern to flag.
    """
    if len(body) != 1:
        return False
    stmt = body[0]
    value = getattr(stmt, "value", None)
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Expr)) and value is not None:
        if isinstance(value, ast.Subscript):
            return True
        if isinstance(value, ast.Call):
            name = getattr(value.func, "id", None) or getattr(value.func, "attr", None)
            return name in PROBE_CALLS
    return False


def _ast_try_in_loop_findings(path: Path, index: PythonIndex) -> Iterator[Finding]:
    """GL031: exceptions used as per-iteration control flow inside a loop —
    a handler whose whole body is `pass` or `continue`, i.e. the exception is
    expected to fire on ordinary input and the raise/unwind cost is paid every
    time round.

    Not "a try inside a loop". Since Python 3.11 a try block that does not
    raise costs nothing at runtime, so the old form of this rule was measuring
    something that stopped existing — and it fired on every retry loop,
    per-item error collector and `except OSError: break` read loop in the
    portfolio, all of which need the handler exactly where it is.

    `seen` dedupes a `try` matched from more than one enclosing loop when
    loops are nested.
    """
    rule = RULES_BY_ID["GL031"]
    seen: set[int] = set()
    for stmt, enclosing in index.tries:
        if not enclosing or stmt.lineno in seen:
            continue
        swallowed = any(all(isinstance(b, (ast.Pass, ast.Continue)) for b in h.body) for h in stmt.handlers)
        if swallowed and _has_cheap_alternative(stmt.body):
            seen.add(stmt.lineno)
            yield _finding(rule, path, stmt.lineno)


