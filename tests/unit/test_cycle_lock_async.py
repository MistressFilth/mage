"""Tests for the PipelineContext cycle lock infrastructure."""

from __future__ import annotations

import threading

from mage.artifacts.mapping import (
    BaseBIDEntry,
    MappingArtifact,
)
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext


def _ctx(tmp_path):
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(
            project_id="p",
            base_bids=[
                BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d"),
            ],
        ),
        events_log=EventsLog(tmp_path / "events.jsonl"),
    )


def test_get_cycle_lock_returns_same_instance(tmp_path):
    ctx = _ctx(tmp_path)
    a = ctx._get_cycle_lock()
    b = ctx._get_cycle_lock()
    assert a is b


def test_get_cycle_lock_threadsafe_init(tmp_path):
    """Concurrent first-touch must yield exactly one lock instance."""
    ctx = _ctx(tmp_path)
    locks = []

    def grab():
        locks.append(ctx._get_cycle_lock())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(l) for l in locks}) == 1
