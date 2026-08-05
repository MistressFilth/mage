"""Plan 25 static guards.

Replaces the narrow Plan 15 decomposition.py sweep with a sweep of the
whole src/mage/ tree. Pins the new EventType member and the new
ReviewBudgetExhausted signature.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from mage.orchestration.events import EventType
from mage.orchestration.inscribe import ReviewBudgetExhausted

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "mage"


def _grep(pattern: str, root: Path) -> list[str]:
    """Return lines matching `pattern` anywhere under `root`."""
    rx = re.compile(pattern)
    out: list[str] = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if rx.search(line):
                out.append(f"{path.relative_to(SRC_ROOT)}:{i}: {line.strip()}")
    return out


def test_no_todo_plan6_in_src_mage() -> None:
    """No TODO(plan6) markers anywhere in src/mage/."""
    matches = _grep(r"TODO\(plan6\)", SRC_ROOT)
    assert matches == [], f"TODO(plan6) found in src/mage/: {matches}"


def test_scenario_halt_persisted_event_type_exists() -> None:
    """EventType.SCENARIO_HALT_PERSISTED must be a member of the enum."""
    assert hasattr(EventType, "SCENARIO_HALT_PERSISTED")
    assert EventType.SCENARIO_HALT_PERSISTED.value == "scenario_halt_persisted"


def test_review_budget_exhausted_has_halted_sub_bids_parameter() -> None:
    """ReviewBudgetExhausted.__init__ gains halted_sub_bids: list[str]."""
    sig = inspect.signature(ReviewBudgetExhausted.__init__)
    assert "halted_sub_bids" in sig.parameters
    param = sig.parameters["halted_sub_bids"]
    # No default value; required argument.
    assert param.default is inspect.Parameter.empty
