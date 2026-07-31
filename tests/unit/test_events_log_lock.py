"""Tests for serialized async EventsLog appends."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.orchestration.events import Event, EventsLog, EventType


def _event(index: int) -> Event:
    return Event(
        timestamp=datetime(2026, 7, 29, 12, 0, index, tzinfo=UTC),
        event_type=EventType.STAGE_STARTED,
        payload={"index": index},
    )


@pytest.mark.asyncio
async def test_concurrent_appends_serialize(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")

    coroutines = [log.append(_event(index)) for index in range(10)]
    await asyncio.gather(*coroutines)

    events = log.read_all()
    assert len(events) == 10
    assert sorted(event.payload["index"] for event in events) == list(range(10))
    assert log._get_lock() is log._get_lock()


@pytest.mark.asyncio
async def test_reads_remain_lock_free(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")

    await log.append(_event(0))
    snapshot_before = log.read_all()
    await log.append(_event(1))

    assert [event.payload["index"] for event in snapshot_before] == [0]
    assert [event.payload["index"] for event in log.read_all()] == [0, 1]
