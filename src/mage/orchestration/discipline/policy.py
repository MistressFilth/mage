"""Pure functions implementing the Three Practices Approved Gate Scope rules.

Six rules (P1-P6) from parent v2 design lines 291-305. Each function is
side-effect-free except for raising exceptions and returning updated Pydantic
models via model_copy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    PostLiveRevisionEntry,
    ReversionLogEntry,
    ScenarioEntry,
)
from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.exceptions import (
    CycleAlreadyInProgress,
    DecompositionOpen,
    ForwardOrderViolation,
    ModelCannotApplyCosmetic,
    NotApprovedForAutomation,
)

# Statuses that satisfy "predecessor finished" for build-order enforcement.
_PREDECESSOR_DONE_STATUSES = frozenset(
    {
        LifecycleStatus.LIVE,
        LifecycleStatus.DEPRECATED,
        LifecycleStatus.RETIRED,
    }
)


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


# P4 — Decomposition closed before any per-scenario cycle starts
def assert_decomposition_closed(plan_path: Path, events_log: EventsLog) -> None:
    """Per-scenario cycles require a finalized Plan (PLAN_FINALIZED or PLAN_REVISED event)."""
    plan_path_str = str(plan_path)
    found = any(
        e.event_type in (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        and e.payload.get("plan_path") == plan_path_str
        for e in events_log.read_all()
    )
    if not found:
        raise DecompositionOpen(
            f"Plan at {plan_path} not finalized; per-scenario cycles blocked"
        )


# P5 — Revision re-applies the gate
def begin_revision(
    mapping: MappingArtifact,
    sub_bid: str,
    reason: str,
    originating_stage: str,
    timestamp: datetime,
) -> MappingArtifact:
    """Revert scenario to inscribing; append ReversionLogEntry."""
    new_entries: list[BaseBIDEntry] = []
    matched = False
    for entry in mapping.base_bids:
        new_scenarios: list[ScenarioEntry] = []
        scenario_found = False
        for scenario in entry.scenarios:
            if scenario.sub_bid == sub_bid:
                scenario_found = True
                new_scenarios.append(
                    scenario.model_copy(
                        update={"lifecycle_status": LifecycleStatus.INSCRIBING}
                    )
                )
            else:
                new_scenarios.append(scenario)
        if scenario_found:
            matched = True
            new_log = [
                *entry.reversion_log,
                ReversionLogEntry(
                    sub_bid=sub_bid,
                    timestamp=timestamp,
                    reason=reason,
                    originating_stage=originating_stage,
                ),
            ]
            new_entries.append(
                entry.model_copy(
                    update={"scenarios": new_scenarios, "reversion_log": new_log}
                )
            )
        else:
            new_entries.append(entry)
    if not matched:
        raise ForwardOrderViolation(
            f"sub_bid {sub_bid!r} not found in mapping; cannot revise"
        )
    return mapping.model_copy(update={"base_bids": new_entries})


# Supersession (full only in v1)
def begin_supersession(
    mapping: MappingArtifact,
    old_sub_bid: str,
    new_sub_bid: str,
    reason: str,
    timestamp: datetime,
) -> MappingArtifact:
    """Mark new scenario as superseding old. Old stays live until new reaches live."""
    new_entries: list[BaseBIDEntry] = []
    for entry in mapping.base_bids:
        new_scenarios = [
            (
                s.model_copy(update={"supersedes": old_sub_bid})
                if s.sub_bid == new_sub_bid
                else s
            )
            for s in entry.scenarios
        ]
        if any(s.sub_bid == old_sub_bid for s in entry.scenarios):
            new_log = [
                *entry.reversion_log,
                ReversionLogEntry(
                    sub_bid=old_sub_bid,
                    timestamp=timestamp,
                    reason=reason,
                    originating_stage="supersession",
                ),
            ]
            new_entries.append(
                entry.model_copy(
                    update={"scenarios": new_scenarios, "reversion_log": new_log}
                )
            )
        else:
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios}))
    return mapping.model_copy(update={"base_bids": new_entries})


def complete_supersession(
    mapping: MappingArtifact,
    new_sub_bid: str,
    timestamp: datetime,
) -> MappingArtifact:
    """Flip old scenario to DEPRECATED when new scenario reaches LIVE."""
    # Find the new scenario's supersedes target
    target_old: str | None = None
    for entry in mapping.base_bids:
        for s in entry.scenarios:
            if s.sub_bid == new_sub_bid:
                target_old = s.supersedes
                break
        if target_old:
            break
    if target_old is None:
        raise ForwardOrderViolation(
            f"new sub_bid {new_sub_bid!r} has no supersedes link"
        )

    new_entries: list[BaseBIDEntry] = []
    for entry in mapping.base_bids:
        new_scenarios: list[ScenarioEntry] = []
        for s in entry.scenarios:
            if s.sub_bid == target_old:
                new_scenarios.append(
                    s.model_copy(
                        update={
                            "lifecycle_status": LifecycleStatus.DEPRECATED,
                            "superseded_by": new_sub_bid,
                        }
                    )
                )
            else:
                new_scenarios.append(s)
        if any(s.sub_bid == target_old for s in entry.scenarios):
            new_log = [
                *entry.reversion_log,
                ReversionLogEntry(
                    sub_bid=target_old,
                    timestamp=timestamp,
                    reason=f"superseded by {new_sub_bid}",
                    originating_stage="supersession_complete",
                ),
            ]
            new_entries.append(
                entry.model_copy(
                    update={"scenarios": new_scenarios, "reversion_log": new_log}
                )
            )
        else:
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios}))
    return mapping.model_copy(update={"base_bids": new_entries})


from mage.artifacts.inspect import CosmeticItem


# Cosmetic gate (parent v2 design line 327)
def guard_cosmetic_application(
    source: str,
    item: CosmeticItem,
    human_approver: str | None,
) -> PostLiveRevisionEntry:
    """Build a PostLiveRevisionEntry. Reject model source; require human approver."""
    if source not in ("human", "human-authorized") or not human_approver:
        raise ModelCannotApplyCosmetic(
            f"cosmetic application source={source!r} with approver={human_approver!r} "
            f"rejected; live-scenario text changes require human authorization"
        )
    from datetime import datetime

    return PostLiveRevisionEntry(
        sub_bid=item.sub_bid,
        timestamp=datetime.now(UTC),
        human_approver=human_approver,
        before_hash="",
        after_hash="",
    )
