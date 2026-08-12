"""AST guards for P32 invariants."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "mage"
EVENTS_PATH = SRC_ROOT / "orchestration" / "events.py"
HOST_CONFIG_PATH = SRC_ROOT / "host_project_config.py"


def _walk_python_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _ast_constant_strings(tree: ast.AST) -> list[tuple[str, str]]:
    """Yield (module_name, literal_value) for every string Constant in tree."""
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(("", node.value))
    return out


def _decorator_is_field_validator(decorator: ast.expr) -> bool:
    """True if decorator is ``@field_validator`` (Name or Call form)."""
    if isinstance(decorator, ast.Name) and decorator.id == "field_validator":
        return True
    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
        return decorator.func.id == "field_validator"
    return False


def test_no_dot_mage_literal_outside_state_migration() -> None:
    """No `'.mage'` string literal in src/mage except state_migration.py."""
    offenders: list[str] = []
    for path in _walk_python_files():
        if path.name == "state_migration.py":
            continue
        tree = ast.parse(path.read_text())
        for _, value in _ast_constant_strings(tree):
            if value == ".mage" or value.startswith((".mage/", ".mage.")):
                offenders.append(f"{path.relative_to(SRC_ROOT)}: literal {value!r}")
    assert not offenders, (
        "'.mage' literals found outside state_migration.py:\n" + "\n".join(offenders)
    )


def test_mage_toml_orphan_branch_has_validator() -> None:
    """MageTomlConfig.orphan_branch has a field_validator enforcing the regex."""
    tree = ast.parse(HOST_CONFIG_PATH.read_text())
    cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "MageTomlConfig"
    )
    validators = [
        node
        for node in ast.walk(cls)
        if isinstance(node, ast.FunctionDef)
        and any(_decorator_is_field_validator(d) for d in node.decorator_list)
    ]
    validator_names = {v.name for v in validators}
    assert "_validate_orphan_branch" in validator_names, (
        f"expected _validate_orphan_branch field_validator; found {validator_names}"
    )


def test_state_store_constructions_pass_regex_compliant_branch() -> None:
    """StateStore(...) constructions pass branch_name matching the regex."""
    pattern = re.compile(r"^[a-zA-Z0-9._/-]+$")
    offenders: list[str] = []
    for path in _walk_python_files():
        if path.name == "state_store.py":
            continue  # the class itself defines the contract
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "StateStore"
            ):
                branch_arg = next(
                    (kw.value for kw in node.keywords if kw.arg == "branch_name"),
                    None,
                )
                if branch_arg is None and len(node.args) >= 2:
                    branch_arg = node.args[1]
                if (
                    isinstance(branch_arg, ast.Constant)
                    and isinstance(branch_arg.value, str)
                    and (
                        not pattern.fullmatch(branch_arg.value)
                        or branch_arg.value.startswith(".")
                        or branch_arg.value.endswith(".lock")
                    )
                ):
                    offenders.append(
                        f"{path.relative_to(SRC_ROOT)}: StateStore(branch_name={branch_arg.value!r})"
                    )
    assert not offenders, "StateStore branch_name violations:\n" + "\n".join(offenders)


def test_required_event_types_exist() -> None:
    """All P32 event types are declared in events.py."""
    tree = ast.parse(EVENTS_PATH.read_text())
    enum_cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "EventType"
    )
    members = {
        node.targets[0].id: node.value.value
        for node in enum_cls.body
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    }
    required = {
        "STATE_STORE_READ",
        "STATE_STORE_WRITE",
        "STATE_STORE_DELETE",
        "STATE_MIGRATED",
        "STATE_MIGRATED_PARTIAL",
        "STATE_MIGRATION_RESTORED",
        "STATE_BOOTSTRAPPED",
    }
    missing = required - set(members.keys())
    assert not missing, f"missing EventType members: {missing}"
