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


def _scenario(
    sub_bid: str, status: LifecycleStatus, supersedes: str | None = None
) -> ScenarioEntry:
    return ScenarioEntry(
        sub_bid=sub_bid,
        scenario_text_hash="h",
        lifecycle_status=status,
        supersedes=supersedes,
    )


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

from datetime import UTC, datetime

from mage.orchestration.discipline.policy import assert_decomposition_closed
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.exceptions import DecompositionOpen


def _log(tmp_path: Path) -> EventsLog:
    return EventsLog(tmp_path / "events.jsonl")


def _emit(log: EventsLog, event_type: EventType, payload: dict) -> None:
    log.append(Event(timestamp=datetime.now(UTC), event_type=event_type, payload=payload))


def test_p4_passes_when_plan_finalized_event_present(tmp_path):
    log = _log(tmp_path)
    _emit(log, EventType.PLAN_FINALIZED, {"plan_path": str(tmp_path / "plan.md"), "plan_sha256": "abc"})
    assert_decomposition_closed(tmp_path / "plan.md", log)  # no raise


def test_p4_passes_when_plan_revised_event_present(tmp_path):
    log = _log(tmp_path)
    _emit(log, EventType.PLAN_REVISED, {"plan_path": str(tmp_path / "plan.md"), "plan_sha256": "abc"})
    assert_decomposition_closed(tmp_path / "plan.md", log)


def test_p4_raises_when_no_finalized_event(tmp_path):
    log = _log(tmp_path)
    with pytest.raises(DecompositionOpen):
        assert_decomposition_closed(tmp_path / "plan.md", log)

from mage.orchestration.discipline.policy import begin_revision


def _now() -> datetime:
    return datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


def test_p5_flips_status_to_inscribing():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED)])
    out = begin_revision(m, "A", "spec ambiguity in step 2", "inspect_loop", _now())
    assert out.lookup_sub_bid(_make_base85("00000"), "A").lifecycle_status == LifecycleStatus.INSCRIBING


def test_p5_appends_reversion_log_entry_to_correct_base_bid_entry():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED)])
    out = begin_revision(m, "A", "reason", "inspect_loop", _now())
    entry = out.base_bids[0]
    assert len(entry.reversion_log) == 1
    assert entry.reversion_log[0].sub_bid == "A"
    assert entry.reversion_log[0].reason == "reason"
    assert entry.reversion_log[0].originating_stage == "inspect_loop"


def test_p5_preserves_earlier_reversions():
    from mage.artifacts.mapping import ReversionLogEntry
    earlier = ReversionLogEntry(sub_bid="A", timestamp=_now(), reason="r1", originating_stage="s1")
    entry = BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d",
                         scenarios=[_scenario("A", LifecycleStatus.APPROVED)],
                         reversion_log=[earlier])
    m = MappingArtifact(project_id="p", base_bids=[entry])
    out = begin_revision(m, "A", "r2", "s2", _now())
    assert len(out.base_bids[0].reversion_log) == 2


def test_p5_raises_when_sub_bid_not_found():
    m = _mapping([])
    with pytest.raises(ForwardOrderViolation):
        begin_revision(m, "MISSING", "r", "s", _now())


# helper for first P5 test
from mage.artifacts.bid import Base85BID


def _make_base85(v: str) -> Base85BID:
    return Base85BID(value=v)


from mage.orchestration.discipline.policy import (
    begin_supersession,
    complete_supersession,
)


def test_supersession_begin_sets_supersedes_link_on_new():
    # old in one base_bid, new in another
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[_scenario("N", LifecycleStatus.INSCRIBING)])
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("O", LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    out = begin_supersession(m, "O", "N", "new spec", _now())
    new = next(s for entry in out.base_bids for s in entry.scenarios if s.sub_bid == "N")
    assert new.supersedes == "O"


def test_supersession_complete_flips_old_to_deprecated():
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[_scenario("N", LifecycleStatus.APPROVED, supersedes="O")])
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("O", LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    out = complete_supersession(m, "N", _now())
    old = next(s for entry in out.base_bids for s in entry.scenarios if s.sub_bid == "O")
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED
    assert old.superseded_by == "N"


def test_supersession_complete_writes_reversion_log_entry():
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[_scenario("N", LifecycleStatus.APPROVED, supersedes="O")])
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("O", LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    out = complete_supersession(m, "N", _now())
    old_entry = next(e for e in out.base_bids if any(s.sub_bid == "O" for s in e.scenarios))
    assert any(log.reason.startswith("superseded by") for log in old_entry.reversion_log)
