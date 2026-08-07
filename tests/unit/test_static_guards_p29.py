"""Static guard for Plan 29 — silent-branch fixes.

P29 closes two P26 Minor findings where functions returned without
emitting any event:
- settle_feature.py:_execute_disposition — `disposition="kept"`
  early-returned silently. Now emits `SETTLE_BRANCH_KEPT` before the
  return.
- etch.py:run_scenario — returned silently when `target.steps` was
  empty. Now emits a final `ETCH_COMPLETED` after the for-loop closes.

The audit-trail invariant is "preceded by an emit" — not just
"preceded by some work". A future silent return after a helper call
(e.g., a `pr_opened`/`merged` path that drops its emit) would still
be a regression. This guard pins the two specific emit-before-exit
sites rather than walking the whole function with a broader predicate.

Narrower than a function-wide walker: this guard only checks the two
sites P29 repaired. If the audit expands to cover additional
silent-branch findings, add a new site-specific check here rather
than relaxing the predicate.
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


def _is_emit_call(node: ast.AST) -> bool:
    """Return True if `node` is an event-emission call.

    Accepts both `self.events_log.append(...)` (the shape used by the
    P29 fixes) and bare `events_log.append(...)` (for parity/reuse).
    Does NOT match arbitrary method calls, helper calls, or assigns —
    the audit-trail invariant is specifically about emits, not
    "observable work".
    """
    # Unwrap `await self.events_log.append(...)`. The caller may pass
    # either an `Expr` wrapping an `Await` wrapping a `Call`, or the
    # inner `Await`/`Call` directly.
    if isinstance(node, ast.Expr):
        inner = node.value
    else:
        inner = node
    if isinstance(inner, ast.Await):
        call = inner.value
    else:
        call = inner
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "append"):
        return False
    # self.events_log.append(...) and bare events_log.append(...)
    return (
        isinstance(func.value, ast.Attribute) and func.value.attr == "events_log"
    ) or (isinstance(func.value, ast.Name) and func.value.id == "events_log")


def _body_has_emit_before_return(stmts: list[ast.stmt]) -> bool:
    """Return True if any emit call in `stmts` appears before the first
    return/raise. Walks into `if`/`for`/`while` bodies because the
    P29 fixes place the emit inside an `if` block followed by a
    top-level `return`."""
    for stmt in stmts:
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            if _body_has_emit_before_return(stmt.body):
                return True
            continue
        if isinstance(stmt, (ast.Return, ast.Raise)):
            return False
        if isinstance(stmt, ast.Expr) and _is_emit_call(stmt):
            return True
    return False


def test_settle_kept_branch_emits_before_return() -> None:
    """The `if disposition == "kept":` branch in
    SettleFeatureStage._execute_disposition must emit
    SETTLE_BRANCH_KEPT before its return statement. The audit-trail
    invariant the P29 finding identified is "no return without a prior
    emit"; this guard pins that structural change."""
    tree = _parse(SRC / "orchestration" / "settle_feature.py")
    cls = _find_class(tree, "SettleFeatureStage")
    assert cls is not None
    method = _find_method(cls, "_execute_disposition")
    assert method is not None

    kept_branch: ast.If | None = None
    for stmt in method.body:
        if (
            isinstance(stmt, ast.If)
            and isinstance(stmt.test, ast.Compare)
            and isinstance(stmt.test.left, ast.Name)
            and stmt.test.left.id == "disposition"
            and any(
                isinstance(c, ast.Constant) and c.value == "kept"
                for c in stmt.test.comparators
            )
        ):
            kept_branch = stmt
            break
    assert kept_branch is not None, (
        'Could not find `if disposition == "kept":` branch in '
        "_execute_disposition; the guard requires the literal to be "
        "present at the AST level."
    )
    assert _body_has_emit_before_return(kept_branch.body), (
        "The `kept` branch must call `events_log.append(...)` before "
        "its `return`; found no emit before the first return/raise. "
        "P29 fix SETTLE_BRANCH_KEPT emission appears to have regressed."
    )


def test_etch_run_scenario_emits_before_return() -> None:
    """EtchStage.run_scenario must emit (a final ETCH_COMPLETED) at
    the function-body level immediately before its `return increments`
    statement. P29 closed the empty-steps silent-branch by adding a
    final emit after the for-loop; this guard pins that emit-before-exit
    structure."""
    tree = _parse(SRC / "orchestration" / "etch.py")
    cls = _find_class(tree, "EtchStage")
    assert cls is not None
    method = _find_method(cls, "run_scenario")
    assert method is not None

    # Locate the top-level `return increments` (or any `return <expr>`).
    return_index: int | None = None
    for i, stmt in enumerate(method.body):
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            return_index = i
            break
    assert return_index is not None, (
        "run_scenario must contain a top-level `return` statement."
    )
    assert return_index > 0, (
        "run_scenario's `return` is the first statement; P29 fix "
        "requires the final ETCH_COMPLETED emit to precede it."
    )

    # The immediately-preceding statement at the function-body level
    # must itself be an emit call (not a helper call, not an assign).
    prev = method.body[return_index - 1]
    assert isinstance(prev, ast.Expr) and _is_emit_call(prev), (
        "The statement immediately before run_scenario's top-level "
        "`return` must be an `events_log.append(...)` emit call. "
        "Found: " + ast.unparse(prev)
    )
