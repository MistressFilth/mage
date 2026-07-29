# tests/unit/test_discipline_policy.py — P1 section
import pytest

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.discipline.policy import assert_independent_gates
from mage.orchestration.exceptions import ForwardOrderViolation


def _scenario(sub_bid: str, status: LifecycleStatus) -> ScenarioEntry:
    return ScenarioEntry(sub_bid=sub_bid, scenario_text_hash="h", lifecycle_status=status)


def _mapping(scenarios: list[ScenarioEntry]) -> MappingArtifact:
    return MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b",
                behavior_description="d",
                scenarios=scenarios,
            )
        ],
    )


def test_p1_passes_when_earlier_live():
    m = _mapping([_scenario("A", LifecycleStatus.LIVE), _scenario("B", LifecycleStatus.INSCRIBING)])
    assert_independent_gates(m, "B")  # no raise


def test_p1_passes_when_earlier_deprecated():
    m = _mapping([_scenario("A", LifecycleStatus.DEPRECATED), _scenario("B", LifecycleStatus.INSCRIBING)])
    assert_independent_gates(m, "B")  # no raise


def test_p1_raises_when_earlier_inscribing():
    m = _mapping([_scenario("A", LifecycleStatus.INSCRIBING), _scenario("B", LifecycleStatus.INSCRIBING)])
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")


def test_p1_raises_when_earlier_approved():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED), _scenario("B", LifecycleStatus.INSCRIBING)])
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")


def test_p1_respects_base_bid_ordering():
    # Scenario "B" in base_bid 00000 declared after "A" in 00001; A must be live first.
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                         scenarios=[_scenario("A", LifecycleStatus.INSCRIBING)]),
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("B", LifecycleStatus.INSCRIBING)]),
        ],
    )
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")

from pathlib import Path

from mage.orchestration.discipline.policy import (
    acquire_cycle_lock,
    release_cycle_lock,
)
from mage.orchestration.exceptions import CycleAlreadyInProgress
from mage.orchestration.nodes import PipelineContext


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=_mapping([]),
        events_log=__import__("mage.orchestration.events", fromlist=["EventsLog"]).EventsLog(tmp_path / "events.jsonl"),
    )


def test_p2_acquire_succeeds_when_unset(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    assert ctx.current_sub_bid == "A"


def test_p2_acquire_raises_when_held_by_other(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    with pytest.raises(CycleAlreadyInProgress):
        acquire_cycle_lock(ctx, "B")


def test_p2_acquire_allows_same_sub_bid_reacquire(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    acquire_cycle_lock(ctx, "A")  # no raise
    assert ctx.current_sub_bid == "A"


def test_p2_release_clears_lock(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    release_cycle_lock(ctx)
    assert ctx.current_sub_bid is None
    acquire_cycle_lock(ctx, "B")  # no raise

from mage.orchestration.discipline.policy import guard_automation_entry
from mage.orchestration.exceptions import NotApprovedForAutomation


def test_p3_passes_when_approved():
    s = _scenario("A", LifecycleStatus.APPROVED)
    guard_automation_entry(s)


def test_p3_raises_when_inscribing():
    s = _scenario("A", LifecycleStatus.INSCRIBING)
    with pytest.raises(NotApprovedForAutomation):
        guard_automation_entry(s)


def test_p3_raises_when_live():
    s = _scenario("A", LifecycleStatus.LIVE)
    with pytest.raises(NotApprovedForAutomation):
        guard_automation_entry(s)
