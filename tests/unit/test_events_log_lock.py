"""Tests for the EventsLog asyncio lock infrastructure."""

from __future__ import annotations

import threading
from pathlib import Path

from mage.orchestration.events import EventsLog


def test_get_lock_returns_same_instance(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    lock_a = log._get_lock()
    lock_b = log._get_lock()
    assert lock_a is lock_b


def test_get_lock_is_threadsafe_init(tmp_path: Path):
    """Concurrent first-touch must yield exactly one lock instance."""
    log = EventsLog(tmp_path / "events.jsonl")
    locks = []

    def grab():
        locks.append(log._get_lock())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(l) for l in locks}) == 1
