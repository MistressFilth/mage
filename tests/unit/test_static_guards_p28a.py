"""Static guards for Plan 28a — settle supersession resolution.

Pins the new event type, the discipline-stage branch, the
extracted helper, the in-settle emission, and the discarded-skip
behaviour against regression. AST-based; no runtime fixtures needed.
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


def _find_method(tree: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_event_type_member(tree: ast.Module, attr: str) -> ast.Assign | None:
    cls = _find_class(tree, "EventType")
    assert cls is not None, "EventType class not found in events.py"
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == attr
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    return node
    return None


# ---------------------------------------------------------------------------
# Guard 1: the new event type member exists with the expected string value
# ---------------------------------------------------------------------------


def test_event_type_supersession_resolved_member_exists() -> None:
    tree = _parse(SRC / "orchestration" / "events.py")
    node = _find_event_type_member(tree, "SCENARIO_SUPERSESSION_RESOLVED")
    assert node is not None, (
        "EventType.SCENARIO_SUPERSESSION_RESOLVED must be defined in events.py"
    )
    assert node.value.value == "scenario_supersession_resolved"  # type: ignore[union-attr, ty:unresolved-attribute]
