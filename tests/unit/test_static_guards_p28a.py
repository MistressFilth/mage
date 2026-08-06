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


# ---------------------------------------------------------------------------
# Guard 2: discipline/stage.py handles the new event
# ---------------------------------------------------------------------------


def _find_method_in_file(
    path: Path, class_name: str, method_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    tree = _parse(path)
    cls = _find_class(tree, class_name)
    assert cls is not None, f"{class_name} not found in {path}"
    return _find_method(cls, method_name)


def test_discipline_stage_handles_supersession_resolved_event() -> None:
    """The new event must have a branch in DisciplineStage._handle_event."""
    method = _find_method_in_file(
        SRC / "orchestration" / "discipline" / "stage.py",
        "DisciplineStage",
        "_handle_event",
    )
    assert method is not None
    found = False
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "et"
            and any(
                isinstance(comp, ast.Attribute)
                and isinstance(comp.value, ast.Name)
                and comp.value.id == "EventType"
                and comp.attr == "SCENARIO_SUPERSESSION_RESOLVED"
                for comp in node.comparators
            )
        ):
            found = True
            break
    assert found, (
        "DisciplineStage._handle_event must check "
        "et == EventType.SCENARIO_SUPERSESSION_RESOLVED"
    )


# ---------------------------------------------------------------------------
# Guard 3: the extracted helper exists and is used by both call sites
# ---------------------------------------------------------------------------


def test_helper_method_extracted_in_discipline_stage() -> None:
    method = _find_method_in_file(
        SRC / "orchestration" / "discipline" / "stage.py",
        "DisciplineStage",
        "_resolve_supersession_for_new_live",
    )
    assert method is not None, (
        "_resolve_supersession_for_new_live must exist on DisciplineStage"
    )


def test_scenario_live_branch_delegates_to_helper() -> None:
    """Regression net: SCENARIO_LIVE handler must call the helper, not
    inline complete_supersession + SCENARIO_DEPRECATED emit."""
    tree = _parse(SRC / "orchestration" / "discipline" / "stage.py")
    cls = _find_class(tree, "DisciplineStage")
    assert cls is not None
    handle = _find_method(cls, "_handle_event")
    assert handle is not None
    src = ast.unparse(handle)
    # The helper must be called from within the SCENARIO_LIVE branch.
    assert "_resolve_supersession_for_new_live" in src
    # And the SCENARIO_LIVE branch must NOT inline complete_supersession
    # calls anymore.
    live_branch = ""
    in_live = False
    for node in ast.walk(handle):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "et"
            and any(
                isinstance(c, ast.Attribute)
                and isinstance(c.value, ast.Name)
                and c.value.id == "EventType"
                and c.attr == "SCENARIO_LIVE"
                for c in node.comparators
            )
        ):
            in_live = True
            live_branch = ast.unparse(node)
    assert in_live, "SCENARIO_LIVE branch not found"
    assert "complete_supersession" not in live_branch, (
        "SCENARIO_LIVE branch must delegate to "
        "_resolve_supersession_for_new_live; do not inline "
        "complete_supersession here."
    )


# ---------------------------------------------------------------------------
# Guard 4: run_settle emits SCENARIO_SUPERSESSION_RESOLVED in the
# disposition != "discarded" branch
# ---------------------------------------------------------------------------


def test_run_settle_emits_supersession_resolved() -> None:
    method = _find_method_in_file(
        SRC / "orchestration" / "settle_feature.py",
        "SettleFeatureStage",
        "run_settle",
    )
    assert method is not None
    src = ast.unparse(method)
    assert "SCENARIO_SUPERSESSION_RESOLVED" in src
    # Must be gated on disposition != "discarded".
    # ast.unparse normalizes string quotes, so accept both single- and
    # double-quoted forms.
    assert 'disposition != "discarded"' in src or "disposition != 'discarded'" in src, (
        "SCENARIO_SUPERSESSION_RESOLVED emission must be gated on "
        "disposition != 'discarded'"
    )
    # Must check new scenario is LIVE before emitting.
    assert "LifecycleStatus.LIVE" in src
