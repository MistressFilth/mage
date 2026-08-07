"""Static guards for P30 substrate invariants.

Pins two invariants:
1. Direct ``os.environ`` reads outside the substrate itself are forbidden.
2. The legacy ``HOST_MODEL_API_KEY`` env var name must not reappear.

Note: the regex ``\\bHOST_MODEL_API_KEY\\b`` correctly rejects the
legacy name as a standalone token but does NOT reject
``MAGE_HOST_MODEL_API_KEY`` (which contains ``HOST_MODEL_API_KEY`` as
a substring); the leading underscore in ``MAGE_`` blocks the word
boundary that ``\\b`` anchors on, so the new name passes the guard.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "mage"
ALLOWED_FILES = frozenset(
    {
        SRC / "xdg.py",
        SRC / "settings.py",
        SRC / "cli.py",
        SRC / "cli_config.py",
    }
)

_LEGACY_ENV_VAR_PATTERN = re.compile(r"\bHOST_MODEL_API_KEY\b")


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_os_environ_outside_substrate() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC):
        if path in ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            target = ast.unparse(func) if hasattr(ast, "unparse") else _unparse(func)
            if target.startswith("os.environ") or target == "os.environ.__getitem__":
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        "Direct os.environ reads forbidden outside "
        f"{sorted(p.name for p in ALLOWED_FILES)}: {offenders}"
    )


def test_no_legacy_env_var_literal() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC):
        text = path.read_text()
        if _LEGACY_ENV_VAR_PATTERN.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"HOST_MODEL_API_KEY (the legacy name) must not appear in src/mage/: {offenders}"
    )


def _unparse(node: ast.AST) -> str:  # pragma: no cover - 3.10 fallback
    if isinstance(node, ast.Attribute):
        return f"{_unparse(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return f"{_unparse(node.value)}[{_unparse(node.slice)}]"
    return ast.dump(node)
