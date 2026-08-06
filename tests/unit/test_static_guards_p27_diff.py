"""Static-guard regression net for the P27 increment-relative diff fix.

Pins:
- RealizeStage.__init__ no longer accepts `command_runner`.
- RealizeStage.run_increment does not invoke subprocess / git.
- _default_command_runner is removed.
- The REALIZE_INCREMENT_DIFF_INCOMPLETE emit uses a literal-dict payload
  with the expected keys (sub_bid, step, warnings).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mage"

REALIZE_PATH = SRC / "orchestration" / "realize.py"

EXPECTED_DIFF_INCOMPLETE_KEYS: frozenset[str] = frozenset(
    {"sub_bid", "step", "warnings"}
)


def _realize_init_signature() -> ast.FunctionDef:
    tree = ast.parse(REALIZE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RealizeStage":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    return item
    raise AssertionError("RealizeStage.__init__ not found")


def test_realize_stage_init_has_no_command_runner_param() -> None:
    init = _realize_init_signature()
    args = init.args
    all_args: list[str] = [a.arg for a in args.args]
    all_args += [a.arg for a in args.kwonlyargs]
    assert "command_runner" not in all_args, (
        f"RealizeStage.__init__ must not accept `command_runner` after P27; "
        f"found in args: {all_args}"
    )


def test_default_command_runner_removed() -> None:
    text = REALIZE_PATH.read_text(encoding="utf-8")
    assert "_default_command_runner" not in text, (
        "_default_command_runner must be removed in P27"
    )


def test_realize_run_increment_does_not_call_subprocess() -> None:
    """No `subprocess.run`, `subprocess.check_*`, or `git diff` invocation."""
    tree = ast.parse(REALIZE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # subprocess.run / subprocess.check_call / subprocess.check_output
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in {"run", "check_call", "check_output", "Popen"}
        ):
            raise AssertionError(
                f"RealizeStage must not call subprocess.{func.attr} after P27 "
                f"(line {node.lineno})"
            )
        # `git ...` shell-style call (list literal starting with "git")
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and func.attr in {"command_runner"}
        ):
            raise AssertionError(
                f"RealizeStage must not use self.command_runner after P27 "
                f"(line {node.lineno})"
            )
    # Also catch inline ["git", ...] invocations through any caller.
    text = REALIZE_PATH.read_text(encoding="utf-8")
    assert '"git"' not in text and "'git'" not in text, (
        "RealizeStage.run_increment must not invoke `git` after P27"
    )


def _walk_diff_incomplete_emits() -> list[frozenset[str] | None]:
    """Walk src/mage for `Event(event_type=EventType.REALIZE_INCREMENT_DIFF_INCOMPLETE, payload={...})` calls."""
    results: list[frozenset[str] | None] = []
    for py_file in sorted(SRC.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name: str | None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            else:
                continue
            if func_name != "Event":
                continue
            payload_node: ast.AST | None = None
            for kw in node.keywords:
                if kw.arg == "event_type":
                    et = kw.value
                    if not (
                        isinstance(et, ast.Attribute)
                        and isinstance(et.value, ast.Name)
                        and et.value.id == "EventType"
                        and et.attr == "REALIZE_INCREMENT_DIFF_INCOMPLETE"
                    ):
                        break
                elif kw.arg == "payload":
                    payload_node = kw.value
            else:
                if isinstance(payload_node, ast.Dict):
                    keys: set[str] = set()
                    ok = True
                    for k in payload_node.keys:
                        if k is None or not (
                            isinstance(k, ast.Constant) and isinstance(k.value, str)
                        ):
                            ok = False
                            break
                        keys.add(k.value)
                    results.append(frozenset(keys) if ok else None)
    return results


def test_diff_incomplete_payload_keys_match_expected() -> None:
    """Every REALIZE_INCREMENT_DIFF_INCOMPLETE emit must carry exactly {sub_bid, step, warnings}."""
    emits = _walk_diff_incomplete_emits()
    assert emits, "expected at least one REALIZE_INCREMENT_DIFF_INCOMPLETE emit site"
    for keys in emits:
        assert keys == EXPECTED_DIFF_INCOMPLETE_KEYS, (
            f"REALIZE_INCREMENT_DIFF_INCOMPLETE payload keys mismatch: "
            f"expected {sorted(EXPECTED_DIFF_INCOMPLETE_KEYS)}, "
            f"got {sorted(keys or ())}"
        )
