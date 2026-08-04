"""EventType additions for cosmetic watcher lifecycle."""

from __future__ import annotations

from mage.orchestration.events import EventType


class TestNewEventTypes:
    def test_remote_stop_requested(self) -> None:
        assert (
            EventType.COSMETIC_WATCHER_REMOTE_STOP_REQUESTED.value
            == "cosmetic_watcher_remote_stop_requested"
        )

    def test_remote_stop_succeeded(self) -> None:
        assert (
            EventType.COSMETIC_WATCHER_REMOTE_STOP_SUCCEEDED.value
            == "cosmetic_watcher_remote_stop_succeeded"
        )

    def test_remote_stop_escalated(self) -> None:
        assert (
            EventType.COSMETIC_WATCHER_REMOTE_STOP_ESCALATED.value
            == "cosmetic_watcher_remote_stop_escalated"
        )

    def test_stale_pid_removed(self) -> None:
        assert (
            EventType.COSMETIC_WATCHER_STALE_PID_REMOVED.value
            == "cosmetic_watcher_stale_pid_removed"
        )
