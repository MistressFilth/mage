"""Tests for the MappingArtifact asyncio lock infrastructure."""

from __future__ import annotations

import threading

from mage.artifacts.mapping import MappingArtifact


def test_get_save_lock_returns_same_instance():
    m = MappingArtifact(project_id="p", base_bids=[])
    a = m._get_save_lock()
    b = m._get_save_lock()
    assert a is b


def test_get_save_lock_threadsafe_init():
    """Concurrent first-touch must yield exactly one lock instance."""
    m = MappingArtifact(project_id="p", base_bids=[])
    locks = []

    def grab():
        locks.append(m._get_save_lock())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(l) for l in locks}) == 1