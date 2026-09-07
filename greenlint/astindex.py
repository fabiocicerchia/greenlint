"""Parsing Python once per file and indexing what the AST rules ask about."""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

# ------------------------------------------------------ python AST index ---


def _parse_python(path: Path, text: str) -> ast.Module | None:
    """Parse `text` into an AST, or None on a syntax error. Shared by every
    AST-based Python rule so each file is only parsed once per scan.
    """
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        return None


class PythonIndex:
    """The nodes every Python AST rule needs, collected in one traversal.

    Six rules each called `ast.walk(tree)` to pick out the handful of node
    types they care about, so a scan walked each file's tree six times over.
    Profiling a 4,000-file scan put ~65% of the entire run inside
    `ast.iter_child_nodes`, which was that redundancy and nothing else.

    `enclosing` is the other half: the rules that ask "is this inside a loop?"
    used to answer it by walking the subtree of every loop, which is quadratic
    in nesting depth. Carrying the loop stack down during the one traversal
    answers the same question by looking up.
    """

    __slots__ = ("classes", "fors", "functions", "loop_scopes", "tree", "tries", "whiles")

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        # (node, enclosing loops) pairs, outermost first.
        self.fors: list[tuple[ast.For, Loops]] = []
        self.whiles: list[tuple[ast.While, Loops]] = []
        self.tries: list[tuple[ast.Try, Loops]] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.classes: list[ast.ClassDef] = []
        # Scopes containing at least one loop of their own. A scope with none
        # cannot produce a GL007 finding, and most functions have none, so this
        # is what lets that rule skip them without walking them to find out.
        self.loop_scopes: set[ast.AST] = set()


# One collector per node kind the index cares about, each returning the loop
# stack and the scope its children are in. A nested def/class/lambda starts a
# scope of its own, which is the boundary `_walk_own` respects and the one GL007
# judges names against; everything else leaves both untouched, which is the
# `collect is None` path in the walk below and by far the commonest one.


# The loops enclosing a node, outermost first, and the signature every
# collector shares. `scope` is the node that owns the code — the module, or the
# def, lambda or class the walk last descended into — not a name.
Loops = tuple[ast.For | ast.While, ...]
Collector = Callable[[PythonIndex, ast.AST, Loops, ast.AST], tuple[Loops, ast.AST]]


def _collect_for(index: PythonIndex, node: ast.AST, loops: Loops, scope: ast.AST) -> tuple[Loops, ast.AST]:
    loop = cast("ast.For", node)
    index.fors.append((loop, loops))
    index.loop_scopes.add(scope)
    return (*loops, loop), scope


def _collect_while(index: PythonIndex, node: ast.AST, loops: Loops, scope: ast.AST) -> tuple[Loops, ast.AST]:
    loop = cast("ast.While", node)
    index.whiles.append((loop, loops))
    index.loop_scopes.add(scope)
    return (*loops, loop), scope


def _collect_try(index: PythonIndex, node: ast.AST, loops: Loops, scope: ast.AST) -> tuple[Loops, ast.AST]:
    index.tries.append((cast("ast.Try", node), loops))
    return loops, scope


def _collect_function(index: PythonIndex, node: ast.AST, loops: Loops, scope: ast.AST) -> tuple[Loops, ast.AST]:
    index.functions.append(cast("ast.FunctionDef | ast.AsyncFunctionDef", node))
    return loops, node


def _collect_class(index: PythonIndex, node: ast.AST, loops: Loops, scope: ast.AST) -> tuple[Loops, ast.AST]:
    index.classes.append(cast("ast.ClassDef", node))
    return loops, node


def _collect_lambda(index: PythonIndex, node: ast.AST, loops: Loops, scope: ast.AST) -> tuple[Loops, ast.AST]:
    return loops, node


_COLLECTORS: dict[type[ast.AST], Collector] = {
    ast.For: _collect_for,
    ast.While: _collect_while,
    ast.Try: _collect_try,
    ast.FunctionDef: _collect_function,
    ast.AsyncFunctionDef: _collect_function,
    ast.ClassDef: _collect_class,
    ast.Lambda: _collect_lambda,
}


def index_python(tree: ast.Module) -> PythonIndex:
    """Build a `PythonIndex` from one breadth-first pass.

    Breadth-first because that is `ast.walk`'s order, and the rules used to
    read their nodes from `ast.walk` — keeping it means each rule still sees
    its nodes in the order it always did.

    The child walk is spelled out rather than left to `ast.iter_child_nodes`,
    which is two nested generators and a `try/except` per node, and it stays
    inline rather than becoming a helper: this is the one place in greenlint
    that runs tens of millions of times in a real scan — it was 20 of 36 seconds
    on the standard library — and a call plus a list per node costs 13% of a
    stdlib scan (11.96 s → 13.54 s, five runs each, `make bench`).
    """
    index = PythonIndex(tree)
    queue: deque[tuple[ast.AST, Loops, ast.AST]] = deque([(tree, (), tree)])
    pop = queue.popleft
    push = queue.append
    while queue:
        node, loops, scope = pop()
        # Exact types, not isinstance: `AsyncFor` and `TryStar` are siblings of
        # `For` and `Try` rather than subclasses, and the rules never matched
        # them. This keeps that true rather than quietly widening them.
        collect = _COLLECTORS.get(type(node))
        if collect is None:
            child_scope = scope
        else:
            loops, child_scope = collect(index, node, loops, scope)
        # Expressions are not descended into: Python has no expression that can
        # contain a statement, so none of the kinds `_COLLECTORS` names can be
        # inside one. That is most of a syntax tree — every name, call, constant
        # and operator — skipped rather than queued and rejected.
        for name in node._fields:
            value: object = getattr(node, name, None)
            if type(value) is list:
                for item in cast("list[object]", value):
                    if isinstance(item, ast.AST) and not isinstance(item, ast.expr):
                        push((item, loops, child_scope))
            elif isinstance(value, ast.AST) and not isinstance(value, ast.expr):
                push((value, loops, child_scope))
    return index


# A nested function, lambda or class body is its own scope: its statements and
# its name bindings belong to it, not to the code that encloses it.
SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _walk_own(node: ast.AST) -> Iterator[ast.AST]:
    """Like `ast.walk`, but never descends into a nested scope.

    `ast.walk` treats a `def` inside a loop as part of the loop, which made a
    `return` in a callback read as "this loop can exit" and a `total = 0` in
    one function silence a rebuild in another.
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, SCOPE_BOUNDARIES):
                continue
            stack.append(child)


def _walk_own_loops(node: ast.AST) -> Iterator[tuple[ast.AST, Loops]]:
    """`_walk_own`, pairing each node with the loops enclosing it in this scope.

    Same reason `PythonIndex` carries a loop stack: asking "is this statement
    inside a loop?" by re-walking the subtree of every loop is quadratic in
    nesting, and the answer is already known on the way down.
    """
    stack: list[tuple[ast.AST, Loops]] = [(node, ())]
    while stack:
        cur, loops = stack.pop()
        yield cur, loops
        inner = (*loops, cur) if isinstance(cur, (ast.For, ast.While)) else loops
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, SCOPE_BOUNDARIES):
                continue
            stack.append((child, inner))


def _loop_can_exit(loop: ast.For | ast.While) -> bool:
    """True if the loop body can leave the loop on a data-dependent condition —
    a `break` belonging to this loop, or a `return`/`raise`.

    `while True:` that drains a paginated API, reads a socket until EOF, or
    consumes an iterator all look like infinite loops and are not: each pass
    does work and the exit depends on what came back. What the energy rule is
    actually after is a loop with no way out and nothing to wait on, which
    pegs a core for as long as the process lives.
    """
    for stmt in loop.body:
        if isinstance(stmt, SCOPE_BOUNDARIES):
            continue  # a callback defined in the loop cannot end it
        for n in _walk_own(stmt):
            if isinstance(n, (ast.Return, ast.Raise)):
                return True
            if isinstance(n, ast.Break) and _nearest_loop(loop, n) is loop:
                return True
    return False


def _nearest_loop(root: ast.AST, target: ast.AST) -> ast.AST:
    """The innermost For/While in `root`'s body that encloses `target`, or
    `root` itself. A `break` inside a nested loop exits that one, not this one.
    """
    found = root
    stack: list[tuple[ast.AST, ast.AST]] = [(root, root)]
    while stack:
        node, owner = stack.pop()
        for child in ast.iter_child_nodes(node):
            if child is target:
                found = owner
                stack.clear()
                break
            # A nested function's `return` belongs to that function, not here.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            nxt = child if isinstance(child, (ast.For, ast.While)) else owner
            stack.append((child, nxt))
    return found


