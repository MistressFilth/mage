"""Static guards for P30 substrate invariants.

Pins two invariants:
1. Direct ``os.environ`` reads outside the substrate itself are forbidden.
   Both the call form (``os.environ.get("FOO")``) and the subscript form
   (``os.environ["FOO"]``) are covered; ``test_guard_catches_both_call_
   and_subscript_forms`` holds the guard to that claim.
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


def _os_environ_offenders(path: Path, tree: ast.AST) -> list[str]:
    """Report every ``os.environ`` read in ``tree``, by line.

    Two node shapes reach the environment, and a walk over one alone is
    a guard with a hole in it:

    - ``ast.Call`` — ``os.environ.get("FOO")``, ``os.getenv("FOO")``
    - ``ast.Subscript`` — ``os.environ["FOO"]``, which never parses as
      a Call and so is invisible to the Call pass.
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = ast.unparse(node.func)
        elif isinstance(node, ast.Subscript):
            target = ast.unparse(node.value)
        else:
            continue
        if target.startswith("os.environ"):
            offenders.append(f"{path}:{node.lineno}")
    return offenders


def test_no_os_environ_outside_substrate() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC):
        if path in ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text())
        offenders.extend(_os_environ_offenders(path.relative_to(REPO_ROOT), tree))
    assert not offenders, (
        "Direct os.environ reads forbidden outside "
        f"{sorted(p.name for p in ALLOWED_FILES)}: {offenders}"
    )


def test_guard_catches_both_call_and_subscript_forms(tmp_path: Path) -> None:
    """The guard itself must trip on each shape it claims to cover.

    Without this, a guard that silently stopped matching would read as
    a passing test forever.
    """
    offending = tmp_path / "_bad.py"
    offending.write_text('import os\nos.environ["FOO"]\nos.environ.get("BAR")\n')
    offenders = _os_environ_offenders(offending, ast.parse(offending.read_text()))
    assert len(offenders) == 2, offenders
    assert offenders[0].endswith(":2")  # the subscript form
    assert offenders[1].endswith(":3")  # the call form

    clean = tmp_path / "_good.py"
    clean.write_text("from mage import settings\nsettings.load_settings()\n")
    assert _os_environ_offenders(clean, ast.parse(clean.read_text())) == []


def test_no_legacy_env_var_literal() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC):
        text = path.read_text()
        if _LEGACY_ENV_VAR_PATTERN.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"HOST_MODEL_API_KEY (the legacy name) must not appear in src/mage/: {offenders}"
    )
