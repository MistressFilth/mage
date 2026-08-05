"""Tests for MappingArtifact.save() emitting MAPPING_SAVED when given an events_log.

Plan 11 Task 2: MappingArtifact.save accepts an optional `events_log` kwarg.
When provided, after the atomic tmp+rename write, it appends a
`MAPPING_SAVED` event whose payload reports the
`feature_cosmetic_queue_size` and `base_bids_count`. When `events_log` is
omitted, save behavior is byte-identical to the pre-Plan-11 implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact
from mage.orchestration.events import EventsLog, EventType


def _base(value: str, name: str = "b") -> BaseBIDEntry:
    return BaseBIDEntry(
        base_bid=value,
        behavior_name=name,
        behavior_description="d",
        behavior_halt=[],
    )


def _cosmetic_entry(feature_id: str, sub_bid: str) -> dict:
    return {
        "feature_id": feature_id,
        "sub_bid": sub_bid,
        "text": "use a constant",
    }


@pytest.mark.asyncio
async def test_mapping_save_emits_mapping_saved_event(tmp_path: Path):
    """With an events_log provided, save() appends a MAPPING_SAVED event
    whose payload reflects the artifact's queue size and base_bids count.
    """
    mapping = MappingArtifact(
        project_id="cosmetic-watch",
        base_bids=[_base("00000"), _base("00001"), _base("00002")],
        feature_cosmetic_queue=[
            _cosmetic_entry("feat-1", "00000-001"),
            _cosmetic_entry("feat-1", "00000-002"),
        ],
    )
    log_path = tmp_path / "events.jsonl"
    log = EventsLog(log_path)

    await mapping.save(tmp_path / "mapping.yaml", events_log=log)

    events = log.read_all()
    assert len(events) == 1
    [event] = events
    assert event.event_type == EventType.MAPPING_SAVED
    assert event.payload == {
        "feature_cosmetic_queue_size": 2,
        "base_bids_count": 3,
    }


@pytest.mark.asyncio
async def test_mapping_save_without_events_log_does_not_emit(tmp_path: Path):
    """Backwards compat: omitting events_log writes the file but emits nothing."""
    mapping = MappingArtifact(
        project_id="no-events",
        base_bids=[_base("00000")],
        feature_cosmetic_queue=[_cosmetic_entry("feat-1", "00000-001")],
    )
    path = tmp_path / "mapping.yaml"

    # No events_log provided; pre-Plan-11 callers must continue to work.
    await mapping.save(path)

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert not (tmp_path / "events.jsonl").exists()
