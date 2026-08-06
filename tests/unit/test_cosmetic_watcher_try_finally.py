"""Unit tests for Plan 28b — cosmetic_watcher run() try/finally scope.

The catch-up _handle_mapping_saved() call inside MappingArtifactWatcher.run()
must fall under the same try/finally that covers the poll loop, so an
uncaught exception during catch-up still emits COSMETIC_WATCHER_STOPPED
and removes the PID file. Before P28b, the catch-up call ran outside
the try: block, leaving the audit trail dangling on a STARTED-without-STOPPED
and the PID file on disk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from mage.cosmetic_pid import pid_file_path
from mage.orchestration.cosmetic_watcher import MappingArtifactWatcher
from mage.orchestration.events import Event, EventsLog, EventType


def _write_mapping(project_dir: Path) -> None:
    """Write a minimal mapping.yaml with no cosmetic_findings (catch-up no-op)."""
    (project_dir / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: p\nbase_bids: []\ncosmetic_findings: []\n"
    )


def _build_watcher(tmp_path: Path) -> tuple[MappingArtifactWatcher, EventsLog]:
    events_log = EventsLog(tmp_path / "events.jsonl")
    return MappingArtifactWatcher(
        project_dir=tmp_path, events_log=events_log, poll_interval_ms=10
    ), events_log


def _read_events(events_log: EventsLog) -> list[Event]:
    return events_log.read_all()


def _validation_error() -> ValidationError:
    """Construct a minimal ValidationError for use as a side_effect."""
    return ValidationError.from_exception_data(
        "MappingArtifact",
        [
            {
                "type": "value_error",
                "loc": ("cosmetic_findings", 0),
                "input": 42,
                "ctx": {"error": "test validation error"},
            }
        ],
    )


@pytest.mark.asyncio
async def test_catchup_uncaught_exception_emits_stopped_and_removes_pid(
    tmp_path: Path,
) -> None:
    """When the catch-up _handle_mapping_saved() raises an uncaught
    exception, COSMETIC_WATCHER_STOPPED must still be emitted and the
    PID file must still be removed."""
    _write_mapping(tmp_path)
    watcher, events_log = _build_watcher(tmp_path)
    # The catch-up RuntimeError still propagates out of run() after
    # the finally completes its cleanup. We expect it so the test
    # can inspect the post-state (one STARTED, one STOPPED, no PID).
    # Patch both apply_for_feature (refiner network) and
    # _handle_mapping_saved itself — the empty queue would otherwise
    # skip apply_for_feature, so the direct patch of
    # _handle_mapping_saved is what actually fires the error.
    with (
        patch(
            "mage.orchestration.cosmetic_watcher.apply_for_feature",
            side_effect=RuntimeError("refiner network error"),
        ),
        patch.object(
            MappingArtifactWatcher,
            "_handle_mapping_saved",
            side_effect=RuntimeError("refiner network error"),
        ),
        pytest.raises(RuntimeError, match="refiner network error"),
    ):
        await watcher.run()

    events = _read_events(events_log)
    started = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STARTED]
    stopped = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STOPPED]
    assert len(started) == 1
    assert len(stopped) == 1
    assert not pid_file_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_catchup_validation_error_emits_stopped_and_removes_pid(
    tmp_path: Path,
) -> None:
    """A pydantic ValidationError that escapes catch-up must still
    trigger STOPPED + PID removal.

    Note: the brief's exact YAML (`{feature_id: 'f', sub_bid: 42}`) does
    NOT trigger a propagating error: `sub_bid` isn't model-validated, so
    the entry is silently filtered inside `_handle_mapping_saved`. We
    instead patch `_handle_mapping_saved` to raise the ValidationError
    that MappingArtifact.load would have raised for malformed data. This
    matches the brief's INTENT (a ValidationError during catch-up must
    trigger cleanup) while still reflecting reality.
    """
    _write_mapping(tmp_path)
    watcher, events_log = _build_watcher(tmp_path)
    # The catch-up ValidationError still propagates out of run() after
    # the finally completes its cleanup. We expect it so the test can
    # inspect the post-state (one STARTED, one STOPPED, no PID).
    with (
        patch.object(
            MappingArtifactWatcher,
            "_handle_mapping_saved",
            side_effect=_validation_error(),
        ),
        pytest.raises(ValidationError),
    ):
        await watcher.run()

    events = _read_events(events_log)
    started = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STARTED]
    stopped = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STOPPED]
    assert len(started) == 1
    assert len(stopped) == 1
    assert not pid_file_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_started_emit_failure_still_cleans_up(tmp_path: Path) -> None:
    """If the COSMETIC_WATCHER_STARTED emit itself raises (e.g., disk full),
    the finally: still runs: no STARTED in the log, one STOPPED, no PID."""
    _write_mapping(tmp_path)
    watcher, events_log = _build_watcher(tmp_path)

    real_append = events_log.append
    call_count = {"n": 0}

    async def flaky_append(event):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # The first append is the STARTED event; let it fail.
            raise RuntimeError("disk full")
        return await real_append(event)

    # The STARTED-append error still propagates out of run() after the
    # finally completes its cleanup. We expect the RuntimeError so
    # the test can inspect post-state assertions (no STARTED, one
    # STOPPED, no PID).
    with (
        patch.object(events_log, "append", side_effect=flaky_append),
        pytest.raises(RuntimeError, match="disk full"),
    ):
        await watcher.run()

    events = _read_events(events_log)
    started = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STARTED]
    stopped = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STOPPED]
    assert len(started) == 0  # the STARTED append raised before log captured it
    assert len(stopped) == 1
    assert not pid_file_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_happy_path_unchanged(tmp_path: Path) -> None:
    """Regression net: the existing happy-path behavior (STARTED then
    catch-up then poll loop then STOPPED on stop()) is preserved."""
    _write_mapping(tmp_path)
    watcher, events_log = _build_watcher(tmp_path)
    watcher._stop = True  # exit the poll loop after one iteration
    await watcher.run()

    events = _read_events(events_log)
    started = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STARTED]
    stopped = [e for e in events if e.event_type == EventType.COSMETIC_WATCHER_STOPPED]
    assert len(started) == 1
    assert len(stopped) == 1
    assert not pid_file_path(tmp_path).exists()
