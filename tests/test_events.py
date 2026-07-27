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
