"""Tests for the events log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mage.orchestration.events import Event, EventsLog, EventType


class TestEvent:
    def test_construction(self):
        event = Event(
            timestamp=datetime(2026, 7, 27, tzinfo=UTC),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "harvest"},
        )
        assert event.event_type == EventType.STAGE_STARTED
        assert event.payload == {"stage": "harvest"}


def test_new_event_types_exist():
    from mage.orchestration.events import EventType
    expected = {
        "DECOMPOSITION_STARTED",
        "DECOMPOSITION_COMPLETED",
        "BEHAVIORS_ENUMERATED",
        "PLAN_FINALIZED",
        "PLAN_REVISED",
        "PLAN_DIGEST_MISMATCH",
        "HALT_PERSISTED",
        "BEHAVIORS_REVISED",
    }
    actual = {member.name for member in EventType}
    missing = expected - actual
    assert not missing, f"missing event types: {missing}"


def test_new_event_types_have_expected_string_values():
    from mage.orchestration.events import EventType
    assert EventType.DECOMPOSITION_STARTED.value == "decomposition_started"
    assert EventType.DECOMPOSITION_COMPLETED.value == "decomposition_completed"
    assert EventType.BEHAVIORS_ENUMERATED.value == "behaviors_enumerated"
    assert EventType.PLAN_FINALIZED.value == "plan_finalized"
    assert EventType.PLAN_REVISED.value == "plan_revised"
    assert EventType.PLAN_DIGEST_MISMATCH.value == "plan_digest_mismatch"
    assert EventType.HALT_PERSISTED.value == "halt_persisted"
    assert EventType.BEHAVIORS_REVISED.value == "behaviors_revised"


def test_plan3_event_types_exist():
    from mage.orchestration.events import EventType
    expected = {
        "INSCRIBE_STARTED",
        "INSCRIBE_COMPLETED",
        "BEHAVIOR_INSCRIBE_STARTED",
        "BEHAVIOR_INSCRIBE_COMPLETED",
        "SCENARIO_DRAFTED",
        "MECHANICAL_PRECHECK_PASSED",
        "MECHANICAL_PRECHECK_FAILED",
        "REVIEWER_VERDICT_RECORDED",
        "REVIEW_AGGREGATE_RECORDED",
        "SCENARIO_APPROVED",
        "SCENARIO_NEEDS_REFACTOR",
        "REVIEW_HALT_PERSISTED",
    }
    actual = {member.name for member in EventType}
    missing = expected - actual
    assert not missing, f"missing event types: {missing}"


def test_plan3_event_type_values():
    from mage.orchestration.events import EventType
    assert EventType.INSCRIBE_STARTED.value == "inscribe_started"
    assert EventType.INSCRIBE_COMPLETED.value == "inscribe_completed"
    assert EventType.BEHAVIOR_INSCRIBE_STARTED.value == "behavior_inscribe_started"
    assert EventType.BEHAVIOR_INSCRIBE_COMPLETED.value == "behavior_inscribe_completed"
    assert EventType.SCENARIO_DRAFTED.value == "scenario_drafted"
    assert EventType.MECHANICAL_PRECHECK_PASSED.value == "mechanical_precheck_passed"
    assert EventType.MECHANICAL_PRECHECK_FAILED.value == "mechanical_precheck_failed"
    assert EventType.REVIEWER_VERDICT_RECORDED.value == "reviewer_verdict_recorded"
    assert EventType.REVIEW_AGGREGATE_RECORDED.value == "review_aggregate_recorded"
    assert EventType.SCENARIO_APPROVED.value == "scenario_approved"
    assert EventType.SCENARIO_NEEDS_REFACTOR.value == "scenario_needs_refactor"
    assert EventType.REVIEW_HALT_PERSISTED.value == "review_halt_persisted"


class TestPlan4EventTypes:
    def test_etch_events_present(self):
        from mage.orchestration.events import EventType
        assert EventType.ETCH_STARTED.value == "etch_started"
        assert EventType.ETCH_RED_CONFIRMED.value == "etch_red_confirmed"
        assert EventType.ETCH_COMPLETED.value == "etch_completed"

    def test_realize_events_present(self):
        from mage.orchestration.events import EventType
        assert EventType.REALIZE_STARTED.value == "realize_started"
        assert EventType.REALIZE_INCREMENT_DONE.value == "realize_increment_done"
        assert EventType.REALIZE_COMPLETED.value == "realize_completed"
        assert EventType.SCENARIO_OUTER_GREEN.value == "scenario_outer_green"
        assert EventType.SCENARIO_LIVE.value == "scenario_live"

    def test_inspect_loop_events_present(self):
        from mage.orchestration.events import EventType
        assert EventType.INSPECT_LOOP_STARTED.value == "inspect_loop_started"
        assert EventType.INSPECT_LOOP_PASSED.value == "inspect_loop_passed"
        assert EventType.INSPECT_LOOP_FAILED.value == "inspect_loop_failed"
        assert EventType.INSPECT_LOOP_COMPLETED.value == "inspect_loop_completed"
        assert EventType.INSPECT_JOURNAL_APPENDED.value == "inspect_journal_appended"
        assert EventType.SCENARIO_HALT_PERSISTED.value == "scenario_halt_persisted"

    def test_inspect_feature_events_placeholders(self):
        """Plan 5 events get placeholder members so the schema is stable."""
        from mage.orchestration.events import EventType
        assert EventType.INSPECT_FEATURE_STARTED.value == "inspect_feature_started"
        assert EventType.INSPECT_FEATURE_FINALIZED.value == "inspect_feature_finalized"


class TestPlan5EventTypes:
    def test_inspect_feature_events_full(self):
        from mage.orchestration.events import EventType
        # Plan 4 added placeholders; Plan 5 adds the rest.
        assert EventType.INSPECT_FEATURE_PASSED.value == "inspect_feature_passed"
        assert EventType.INSPECT_FEATURE_HALT_PERSISTED.value == "inspect_feature_halt_persisted"
        assert EventType.INSPECT_FEATURE_COMPLETED.value == "inspect_feature_completed"
        assert EventType.FIX_WAVE_DISPATCHED.value == "fix_wave_dispatched"

    def test_settle_feature_events(self):
        from mage.orchestration.events import EventType
        assert EventType.SETTLE_FEATURE_STARTED.value == "settle_feature_started"
        assert EventType.SETTLE_COSMETIC_QUEUED.value == "settle_cosmetic_queued"
        assert EventType.SETTLE_TESTS_FAILED.value == "settle_tests_failed"
        assert EventType.SETTLE_FEATURE_FINALIZED.value == "settle_feature_finalized"
        assert EventType.SETTLE_FEATURE_COMPLETED.value == "settle_feature_completed"
        assert EventType.SETTLE_BRANCH_DISCARDED.value == "settle_branch_discarded"


class TestEventsLog:
    def test_init_creates_file(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        EventsLog(log_path)
        log_path.touch()  # Ensure file exists for empty-log case
        assert log_path.exists()

    def test_append_and_read_all(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "harvest"},
        ))
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 5, tzinfo=UTC),
            event_type=EventType.STAGE_COMPLETED,
            payload={"stage": "harvest"},
        ))
        events = log.read_all()
        assert len(events) == 2
        assert events[0].event_type == EventType.STAGE_STARTED
        assert events[1].event_type == EventType.STAGE_COMPLETED

    def test_read_empty_log(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log_path.touch()
        log = EventsLog(log_path)
        assert log.read_all() == []

    def test_read_since(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        cutoff = datetime(2026, 7, 27, 10, 2, tzinfo=UTC)
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "harvest"},
        ))
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 5, tzinfo=UTC),
            event_type=EventType.STAGE_COMPLETED,
            payload={"stage": "harvest"},
        ))
        events = log.read_since(cutoff)
        assert len(events) == 1
        assert events[0].event_type == EventType.STAGE_COMPLETED

    def test_log_is_append_only(self, tmp_path: Path):
        # After appends, no in-place edits to the file.
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        log.append(Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.STAGE_STARTED,
            payload={},
        ))
        original = log_path.read_text()
        log.append(Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.STAGE_COMPLETED,
            payload={},
        ))
        # First event's JSON line is unchanged in the file.
        lines = log_path.read_text().splitlines()
        assert len(lines) == 2
        assert original.splitlines()[0] == lines[0]
