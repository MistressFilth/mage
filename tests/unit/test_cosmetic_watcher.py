"""Unit tests for the cosmetic watcher."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.cosmetic_watcher import MappingArtifactWatcher
from mage.orchestration.events import Event, EventType, EventsLog


def _write_mapping(project_dir: Path, *, feature_id: str = "feat-1", sub_bid: str = "00000-001") -> None:
    import yaml

    mapping = {
        "schema_version": 2,
        "project_id": "p",
        "base_bids": [],
        "feature_cosmetic_queue": [
            {
                "feature_id": feature_id,
                "sub_bid": sub_bid,
                "text": "use a constant",
                "location": {"file": "src/example.py", "line": 1},
                "proposed_by": "human",
            }
        ],
    }
    (project_dir / "mapping.yaml").write_text(yaml.safe_dump(mapping))


@pytest.mark.asyncio
async def test_watcher_emits_started_on_run(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    watcher = MappingArtifactWatcher(tmp_path, events_log=log, poll_interval_ms=10)
    watcher.stop()  # exit immediately
    await watcher.run()

    events = log.read_all()
    types = [e.event_type for e in events]
    assert EventType.COSMETIC_WATCHER_STARTED in types
    assert EventType.COSMETIC_WATCHER_STOPPED in types


@pytest.mark.asyncio
async def test_watcher_diffs_queue_and_calls_apply(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    log.log_path.parent.mkdir(parents=True, exist_ok=True)
    log.log_path.write_text("")
    _write_mapping(tmp_path)

    watcher = MappingArtifactWatcher(tmp_path, events_log=log, poll_interval_ms=10)
    with patch(
        "mage.orchestration.cosmetic_watcher.apply_for_feature",
        new_callable=AsyncMock,
    ) as mock_apply:
        mock_apply.return_value = 0
        # Start the watcher BEFORE appending the event so its poll loop
        # sees the new bytes. (The watcher captures file size at run() entry.)
        run_task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.02)  # let watcher emit STARTED + enter poll loop
        await log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.MAPPING_SAVED,
                payload={"feature_cosmetic_queue_size": 1, "base_bids_count": 0},
            )
        )
        await asyncio.sleep(0.05)
        watcher.stop()
        await run_task

    mock_apply.assert_called_once()
    args, kwargs = mock_apply.call_args
    assert args[1] == "feat-1" or kwargs.get("feature_id") == "feat-1"


@pytest.mark.asyncio
async def test_watcher_skips_unchanged_features(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    log.log_path.parent.mkdir(parents=True, exist_ok=True)
    log.log_path.write_text("")
    _write_mapping(tmp_path)

    watcher = MappingArtifactWatcher(tmp_path, events_log=log, poll_interval_ms=10)
    with patch(
        "mage.orchestration.cosmetic_watcher.apply_for_feature",
        new_callable=AsyncMock,
    ) as mock_apply:
        mock_apply.return_value = 0
        run_task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.02)  # let watcher emit STARTED + enter poll loop
        await log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.MAPPING_SAVED,
                payload={},
            )
        )
        await asyncio.sleep(0.05)
        await log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.MAPPING_SAVED,
                payload={},
            )
        )
        await asyncio.sleep(0.05)
        watcher.stop()
        await run_task

    assert mock_apply.call_count == 1


@pytest.mark.asyncio
async def test_watcher_stop_emits_stopped_event(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    watcher = MappingArtifactWatcher(tmp_path, events_log=log, poll_interval_ms=10)
    watcher.stop()
    await watcher.run()
    events = log.read_all()
    assert any(
        e.event_type == EventType.COSMETIC_WATCHER_STOPPED for e in events
    )


@pytest.mark.asyncio
async def test_mapping_save_emits_mapping_saved_event(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(schema_version=2, project_id="p")
    await mapping.save(tmp_path / "mapping.yaml", events_log=log)
    events = log.read_all()
    assert any(e.event_type == EventType.MAPPING_SAVED for e in events)
