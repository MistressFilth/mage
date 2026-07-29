"""Pure functions implementing the Three Practices Approved Gate Scope rules.

Six rules (P1-P6) from parent v2 design lines 291-305. Each function is
side-effect-free except for raising exceptions and returning updated Pydantic
models via model_copy.
"""

from __future__ import annotations

from datetime import datetime

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    PostLiveRevisionEntry,
    ReversionLogEntry,
    ScenarioEntry,
)
from mage.artifacts.plan import PlanArtifact, PlanNotFinalizedError
from mage.orchestration.events import EventsLog
from mage.orchestration.exceptions import (
    CycleAlreadyInProgress,
    DecompositionOpen,
    ForwardOrderViolation,
    ModelCannotApplyCosmetic,
    NotApprovedForAutomation,
)

# Statuses that satisfy "predecessor finished" for build-order enforcement.
_PREDECESSOR_DONE_STATUSES = frozenset({
    LifecycleStatus.LIVE,
    LifecycleStatus.DEPRECATED,
    LifecycleStatus.RETIRED,
})


def _all_scenarios(mapping: MappingArtifact) -> list[ScenarioEntry]:
    """Flatten scenarios across base_bids in declared order."""
    out: list[ScenarioEntry] = []
    for entry in mapping.base_bids:
        out.extend(entry.scenarios)
    return out


def _find_entry_for_sub_bid(
    mapping: MappingArtifact, sub_bid: str
) -> tuple[BaseBIDEntry, int]:
    """Return (entry, scenario_index) for the given sub_bid. Raise if absent."""
    for entry in mapping.base_bids:
        for idx, scenario in enumerate(entry.scenarios):
            if scenario.sub_bid == sub_bid:
                return entry, idx
    raise ForwardOrderViolation(f"sub_bid {sub_bid!r} not found in mapping")


# P1 — Per-scenario independence
def assert_independent_gates(mapping: MappingArtifact, sub_bid: str) -> None:
    """Scenario `sub_bid` may start only if every earlier scenario is done."""
    all_scenarios = _all_scenarios(mapping)
    target_index = next(
        (i for i, s in enumerate(all_scenarios) if s.sub_bid == sub_bid),
        None,
    )
    if target_index is None:
        raise ForwardOrderViolation(f"sub_bid {sub_bid!r} not found in mapping")
    for earlier in all_scenarios[:target_index]:
        if earlier.lifecycle_status not in _PREDECESSOR_DONE_STATUSES:
            raise ForwardOrderViolation(
                f"sub_bid {sub_bid!r} cannot start: earlier scenario "
                f"{earlier.sub_bid!r} has status {earlier.lifecycle_status.value!r}; "
                f"expected one of {sorted(s.value for s in _PREDECESSOR_DONE_STATUSES)}"
            )

from mage.orchestration.nodes import PipelineContext


# P2 — Sequential per-scenario cycles
def acquire_cycle_lock(context: PipelineContext, sub_bid: str) -> None:
    """Acquire the cycle lock for `sub_bid`. Reacquire by same sub_bid is allowed."""
    if context.current_sub_bid is not None and context.current_sub_bid != sub_bid:
        raise CycleAlreadyInProgress(
            f"cycle lock held by sub_bid {context.current_sub_bid!r}; "
            f"cannot start {sub_bid!r}"
        )
    # PipelineContext is mutable; direct assignment is the existing pattern.
    context.current_sub_bid = sub_bid


def release_cycle_lock(context: PipelineContext) -> None:
    """Release the cycle lock. Safe to call when unset."""
    context.current_sub_bid = None


# P3 — Approved before any Etch/Realize sub-phase
def guard_automation_entry(scenario: ScenarioEntry) -> None:
    """Automation sub-phases require scenario.lifecycle_status == APPROVED."""
    if scenario.lifecycle_status != LifecycleStatus.APPROVED:
        raise NotApprovedForAutomation(
            f"scenario {scenario.sub_bid!r} has status "
            f"{scenario.lifecycle_status.value!r}; must be APPROVED before Automation"
        )
