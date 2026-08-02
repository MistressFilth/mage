"""Static guard: enforce zero ruff + zero pyright errors after Plan 19.

Mirrors the Plan 13/15/17/18 static-guard pattern. Asserts that the
make check gate can actually gate. If a future commit regresses lint
or typecheck, this test fails.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class TestLintBaseline:
    def test_ruff_check_passes(self):
        result = _run(["uv", "run", "ruff", "check", "src", "tests"])
        assert result.returncode == 0, (
            f"ruff check failed with {result.returncode} errors:\n{result.stdout}"
        )

    def test_pyright_passes(self):
        result = _run(["uv", "run", "pyright", "src", "tests"])
        assert result.returncode == 0, (
            f"pyright failed with {result.returncode} errors:\n{result.stdout}"
        )
