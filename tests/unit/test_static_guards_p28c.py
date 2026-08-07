"""Static guard for Plan 28c — inspect loop completion events.

Pins the wiring of INSPECT_LOOP_PASSED, INSPECT_LOOP_FAILED, and
INSPECT_LOOP_COMPLETED in InspectLoopStage.inspect_increment so a
future refactor that silently drops one of the completion emits trips
the guard before merge.
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


def _has_event_type_emit(
    method: ast.FunctionDef | ast.AsyncFunctionDef, attr: str
) -> bool:
    """Return True if `EventType.<attr>` is referenced anywhere inside method."""
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "EventType"
            and node.attr == attr
        ):
            return True
    return False


def _has_naked_return_or_raise(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Return a list of code-source snippets for `return X` or `raise Y`
    statements that are NOT preceded by an `events_log.append(...)` or
    `_emit(...)` call in the immediately-preceding statement.

    Best-effort: walks the top-level statements of the method body. Nested
    if/for bodies are walked recursively with the same heuristic.
    """
    found: list[str] = []

    def check_body(stmts: list[ast.stmt]) -> None:
        for i, stmt in enumerate(stmts):
            is_terminal = isinstance(stmt, (ast.Return, ast.Raise))
            if not is_terminal:
                # Recurse into if/while/for bodies.
                if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                    check_body(stmt.body)
                    check_body(stmt.orelse)
                continue
            # Check the immediately-preceding statement (if any) for an emit call.
            if i > 0 and _is_emit_call(stmts[i - 1]):
                continue
            found.append(ast.unparse(stmt))

    def _is_emit_call(node: ast.stmt) -> bool:
        if not isinstance(node, ast.Expr):
            return False
        if not isinstance(node.value, ast.Await):
            return False
        call = node.value.value
        if not isinstance(call, ast.Call):
            return False
        func = call.func
        # Pattern: `await events_log.append(...)` (events_log is a free Name).
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "events_log"
            and func.attr == "append"
        ):
            return True
        # Pattern: `await self.events_log.append(...)` (Attribute-on-Attribute).
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "append"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "events_log"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
        ):
            return True
        # Pattern: `await self._emit(...)`.
        return (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and func.attr == "_emit"
        )

    check_body(method.body)
    return found


def test_inspect_increment_emits_passed() -> None:
    tree = _parse(SRC / "orchestration" / "inspect_loop.py")
    cls = _find_class(tree, "InspectLoopStage")
    assert cls is not None
    method = _find_method(cls, "inspect_increment")
    assert method is not None
    assert _has_event_type_emit(method, "INSPECT_LOOP_PASSED"), (
        "INSPECT_LOOP_PASSED must be emitted somewhere in inspect_increment"
    )


def test_inspect_increment_emits_failed() -> None:
    tree = _parse(SRC / "orchestration" / "inspect_loop.py")
    cls = _find_class(tree, "InspectLoopStage")
    assert cls is not None
    method = _find_method(cls, "inspect_increment")
    assert method is not None
    assert _has_event_type_emit(method, "INSPECT_LOOP_FAILED"), (
        "INSPECT_LOOP_FAILED must be emitted somewhere in inspect_increment"
    )


def test_inspect_increment_emits_completed() -> None:
    tree = _parse(SRC / "orchestration" / "inspect_loop.py")
    cls = _find_class(tree, "InspectLoopStage")
    assert cls is not None
    method = _find_method(cls, "inspect_increment")
    assert method is not None
    assert _has_event_type_emit(method, "INSPECT_LOOP_COMPLETED"), (
        "INSPECT_LOOP_COMPLETED must be emitted somewhere in inspect_increment"
    )


def test_inspect_increment_has_no_naked_return_or_raise() -> None:
    """Every return or raise statement must be preceded by an events_log.append()
    or self._emit(...) call. The StageNode._emit and direct events_log.append
    patterns both count."""
    tree = _parse(SRC / "orchestration" / "inspect_loop.py")
    cls = _find_class(tree, "InspectLoopStage")
    assert cls is not None
    method = _find_method(cls, "inspect_increment")
    assert method is not None
    naked = _has_naked_return_or_raise(method)
    assert naked == [], (
        "Every return/raise in inspect_increment must be preceded by an emit call; "
        f"found naked: {naked}"
    )
