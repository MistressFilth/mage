"""Static-guard regression nets for Plan 15 (approval gate placeholder closure)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mage"


def _grep(pattern: str, path: Path) -> list[str]:
    """Return the list of file paths under path matching pattern (text search)."""
    result = subprocess.run(
        ["grep", "-rln", "--include=*.py", pattern, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_no_plan6_todo_in_decomposition():
    target = SRC / "orchestration" / "decomposition.py"
    matches = _grep(r"TODO\(plan6\)", target)
    assert matches == [], f"TODO(plan6) found in decomposition.py: {matches}"


def test_no_warnings_import_in_decomposition():
    target = SRC / "orchestration" / "decomposition.py"
    text = target.read_text(encoding="utf-8")
    assert not re.search(r"^\s*import\s+warnings\b", text, re.MULTILINE), (
        "`import warnings` should be removed from decomposition.py"
    )
    assert not re.search(r"warnings\.warn", text), (
        "`warnings.warn` should be removed from decomposition.py"
    )
