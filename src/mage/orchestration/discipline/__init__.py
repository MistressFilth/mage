"""Three Practices discipline enforcement.

Package contents:
- policy: pure functions for the six Approved Gate Scope rules + revision +
  supersession + cosmetic guard.
- stage: DisciplineStage (Pydantic-Graph node) that wires policy into the
  event stream.
"""

from __future__ import annotations

from mage.orchestration.discipline.policy import (
    acquire_cycle_lock,
    assert_decomposition_closed,
    assert_independent_gates,
    begin_revision,
    begin_supersession,
    complete_supersession,
    guard_automation_entry,
    guard_cosmetic_application,
    release_cycle_lock,
)
from mage.orchestration.discipline.stage import DisciplineStage

__all__ = [
    "DisciplineStage",
    "acquire_cycle_lock",
    "assert_decomposition_closed",
    "assert_independent_gates",
    "begin_revision",
    "begin_supersession",
    "complete_supersession",
    "guard_automation_entry",
    "guard_cosmetic_application",
    "release_cycle_lock",
]
