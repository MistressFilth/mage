"""Static guard for Plan 29 — silent-branch fixes.

P29 closes two P26 Minor findings where functions returned without
emitting any event:
- settle_feature.py:443 — disposition="kept" early-returned silently.
- etch.py:71 — run_scenario returned silently when target.steps was empty.

This guard walks both functions and asserts every return/raise is
preceded by an observable action (an emit or a method call). The
audit's "silent branch" semantic is "a path that returns without
doing observable work", so the check accepts any preceding statement
that is an `ast.Expr` (i.e., an awaited/called expression). The walker
ignores `try/except/finally` and `with` bodies (none of the guarded
functions use them).

Deviation note: the original P28c-style walker in the plan
recurses via `ast.iter_child_nodes`, which never recurses into a
top-level `if` inside the method body — so it never actually
checks anything. This version recurses into `stmt` itself when it
is an `If`/`For`/`While`, matching P28c's `inspect_increment` guard.

Deviation note: the plan's P28c-style "emit-only" check would
flag the `pr_opened` and `merged` paths in `_execute_disposition`
because their returns are preceded by `_run_checked(...)` and
`_merge(...)` calls, not emits. The audit's intent is "no silent
branch" (no return without observable work), so this guard accepts
any preceding `ast.Expr` — emits, method calls, and awaited method
calls all count.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "mage"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_method(
    tree: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    return None


def _is_preceding_action(node: ast.stmt) -> bool:
    """Return True if `node` is an expression statement that performs an
    observable action (an emit, method call, or awaited call).

    StageNode._emit and `self.events_log.append(...)` are the two emit
    patterns; both count. Bare assignments, control flow, and
    docstrings do not count — the return after them is "naked" because
    no observable work happened in that block.
    """
    if not isinstance(node, ast.Expr):
        return False
    return isinstance(node.value, (ast.Await, ast.Call))


def _naked_returns_or_raises(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    found: list[str] = []

    def check_body(stmts: list[ast.stmt]) -> None:
        for i, stmt in enumerate(stmts):
            is_terminal = isinstance(stmt, (ast.Return, ast.Raise))
            if not is_terminal:
                # Recurse into if/while/for bodies when the statement itself
                # is one of those constructs. Nested `if`s inside larger
                # expressions (e.g., ternaries) are not relevant here.
                if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                    check_body(stmt.body)
                    check_body(stmt.orelse)
                continue
            if i > 0 and _is_preceding_action(stmts[i - 1]):
                continue
            found.append(ast.unparse(stmt))

    check_body(method.body)
    return found


def test_settle_execute_disposition_has_no_naked_return() -> None:
    """Every return/raise in SettleFeatureStage._execute_disposition must be
    preceded by an observable action (an emit or method call). The
    `kept` disposition was the P29 silent-branch fix; this guard pins it."""
    tree = _parse(SRC / "orchestration" / "settle_feature.py")
    cls = _find_class(tree, "SettleFeatureStage")
    assert cls is not None
    method = _find_method(cls, "_execute_disposition")
    assert method is not None
    naked = _naked_returns_or_raises(method)
    assert naked == [], (
        "Every return/raise in _execute_disposition must be preceded by an "
        f"observable action; found naked: {naked}"
    )


def test_etch_run_scenario_has_no_naked_return() -> None:
    """Every return/raise in EtchStage.run_scenario must be preceded by an
    observable action. The empty-steps silent-branch fix added a final
    emit before the return; this guard pins that structural change."""
    tree = _parse(SRC / "orchestration" / "etch.py")
    cls = _find_class(tree, "EtchStage")
    assert cls is not None
    method = _find_method(cls, "run_scenario")
    assert method is not None
    naked = _naked_returns_or_raises(method)
    assert naked == [], (
        "Every return/raise in run_scenario must be preceded by an observable "
        f"action; found naked: {naked}"
    )
