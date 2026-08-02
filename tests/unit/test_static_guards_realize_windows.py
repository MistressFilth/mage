"""Static guard: keep RealizeStage's journal-window knobs on HostConfig.

Mirrors the Plan 18 / Plan 13 / Plan 17 static-guard pattern (see
test_static_guards_cosmetic_rename.py).

Three anti-revert assertions:

1. The pre-PR module constants DEFAULT_PER_SCENARIO_WINDOW and
   DEFAULT_CROSS_SCENARIO_WINDOW must not exist anywhere in realize.py.
2. RealizeStage.__init__ must not accept per_scenario_window or
   cross_scenario_window as parameters — only host_config.
3. The two field names must appear in HostConfig (host_overrides.py).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
REALIZE = REPO_ROOT / "src/mage/orchestration/realize.py"
HOST_OVERRIDES = REPO_ROOT / "src/mage/verification/host_overrides.py"

_REALIZE = str(Path(SRC) / "mage" / "orchestration" / "realize.py")


def _grep(pattern: str, *paths: Path) -> list[str]:
    """Return list of 'path:line' hits for `pattern` in the given paths.

    Excludes this test file from the result so the guard does not match
    its own docstrings/comments that name the constants.
    """
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", pattern, *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line
        for line in result.stdout.splitlines()
        if line and "test_static_guards_realize_windows.py" not in line
    ]


class TestNoModuleWindowConstants:
    def test_default_per_scenario_window_constant_gone(self):
        hits = _grep(r"\bDEFAULT_PER_SCENARIO_WINDOW\b", REALIZE)
        assert hits == [], (
            "DEFAULT_PER_SCENARIO_WINDOW returned to realize.py; "
            "windows must come from HostConfig per the Plan 6 follow-up:\n"
            + "\n".join(hits)
        )

    def test_default_cross_scenario_window_constant_gone(self):
        hits = _grep(r"\bDEFAULT_CROSS_SCENARIO_WINDOW\b", REALIZE)
        assert hits == [], (
            "DEFAULT_CROSS_SCENARIO_WINDOW returned to realize.py; "
            "windows must come from HostConfig per the Plan 6 follow-up:\n"
            + "\n".join(hits)
        )


class TestRealizeStageSignature:
    def test_init_does_not_take_window_kwargs(self):
        """parse realize.py; assert RealizeStage.__init__ has no per_<window>
        parameters and does have host_config."""
        tree = ast.parse(Path(_REALIZE).read_text())
        realize_cls = next(
            node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "RealizeStage"
        )
        init = next(
            node
            for node in realize_cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        params = {a.arg for a in init.args.args + init.args.kwonlyargs}
        assert "per_scenario_window" not in params, (
            "RealizeStage.__init__ still accepts per_scenario_window; "
            "windows must come from HostConfig only."
        )
        assert "cross_scenario_window" not in params, (
            "RealizeStage.__init__ still accepts cross_scenario_window; "
            "windows must come from HostConfig only."
        )
        assert "host_config" in params, (
            "RealizeStage.__init__ no longer takes host_config; re-add it."
        )


class TestHostConfigWindowsPresent:
    def test_host_config_declares_both_window_fields(self):
        text = HOST_OVERRIDES.read_text()
        assert re.search(r"^\s*per_scenario_window\s*:\s*int\s*=", text, re.MULTILINE), (
            "HostConfig no longer declares per_scenario_window; the Plan 6 "
            "follow-up typed field must stay."
        )
        assert re.search(r"^\s*cross_scenario_window\s*:\s*int\s*=", text, re.MULTILINE), (
            "HostConfig no longer declares cross_scenario_window; the Plan 6 "
            "follow-up typed field must stay."
        )
