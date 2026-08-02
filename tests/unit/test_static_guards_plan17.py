"""Static-guard regression nets for Plan 17
(`InspectFeatureStage._run` removal).

Locks in the absence of `def _run(` and any reference to the
`StageNode` base class inside `inspect_feature.py`. Mirrors
Plan 14 (`tests/features/test_e2e_settle_supersession.py`) and
Plan 15 (`tests/unit/test_static_guards_plan15.py`) net patterns.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mage"
TARGET = SRC / "orchestration" / "inspect_feature.py"


def _grep(pattern: str, path: Path) -> list[str]:
    """Return list of `.py` file paths under `path` matching `pattern`."""
    result = subprocess.run(
        ["grep", "-rln", "--include=*.py", pattern, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_no__run_method_in_inspect_feature():
    """`def _run(` must not appear anywhere in `inspect_feature.py`."""
    matches = _grep(r"def _run(", TARGET)
    assert matches == [], (
        f"`def _run(` found in inspect_feature.py after Plan 17: {matches}"
    )


def test_no_StageNode_reference_in_inspect_feature():
    """`StageNode` must not appear in `inspect_feature.py`."""
    text = TARGET.read_text(encoding="utf-8")
    assert not re.search(r"\bStageNode\b", text), (
        "`StageNode` reference found in inspect_feature.py after Plan 17"
    )
