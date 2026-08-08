"""PID file lifecycle helper tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mage.cosmetic_pid import (
    _proc_start_time,
    is_alive,
    is_alive_with_start,
    pid_file_path,
    read_pid,
    remove_pid,
    write_pid,
)


@pytest.fixture
def mage_dir(tmp_path: Path) -> Path:
    (tmp_path / ".mage").mkdir()
    return tmp_path


class TestPath:
    def test_pid_file_path(self, mage_dir: Path) -> None:
        assert pid_file_path(mage_dir) == mage_dir / ".mage" / "cosmetic_watcher.pid"


class TestWrite:
    def test_writes_pid_with_colon_format(self, mage_dir: Path) -> None:
        """The on-disk format is `<pid>:<start_time>\\n`."""
        path = write_pid(mage_dir, 12345)
        assert path == mage_dir / ".mage" / "cosmetic_watcher.pid"
        text = path.read_text()
        # Must be parseable as pid:start_time
        head, _, tail = text.strip().partition(":")
        assert int(head) == 12345
        # start_time is present (empty on non-Linux or unreadable /proc).
        assert tail == "" or tail.isdigit()

    def test_captures_start_time_for_current_process(self, mage_dir: Path) -> None:
        """write_pid records the live process's start_time."""
        write_pid(mage_dir, os.getpid())
        parsed = read_pid(mage_dir)
        assert parsed is not None
        pid, start_time = parsed
        assert pid == os.getpid()
        assert start_time is not None
        assert start_time > 0

    def test_writes_to_nested_path(self, tmp_path: Path) -> None:
        # write_pid creates .mage/ if missing
        path = write_pid(tmp_path, 9999)
        assert path.exists()
        assert (tmp_path / ".mage").is_dir()


class TestRead:
    def test_returns_none_when_missing(self, mage_dir: Path) -> None:
        assert read_pid(mage_dir) is None

    def test_returns_tuple_when_present(self, mage_dir: Path) -> None:
        write_pid(mage_dir, 4242)
        parsed = read_pid(mage_dir)
        assert parsed is not None
        pid, start_time = parsed
        assert pid == 4242
        # psutil.Process.create_time() returns a float Unix timestamp
        # with sub-second precision; accept int or float (legacy or new).
        assert isinstance(start_time, (int, float, type(None)))

    def test_returns_none_on_garbage(self, mage_dir: Path) -> None:
        path = pid_file_path(mage_dir)
        path.write_text("not-a-pid\n")
        assert read_pid(mage_dir) is None

    def test_legacy_format_returns_none_start_time(self, mage_dir: Path) -> None:
        """Legacy single-integer files parse with start_time=None."""
        path = pid_file_path(mage_dir)
        path.write_text("12345\n")
        parsed = read_pid(mage_dir)
        assert parsed == (12345, None)


class TestRemove:
    def test_returns_false_when_missing(self, mage_dir: Path) -> None:
        assert remove_pid(mage_dir) is False

    def test_removes_when_present(self, mage_dir: Path) -> None:
        write_pid(mage_dir, 1)
        assert remove_pid(mage_dir) is True
        assert not pid_file_path(mage_dir).exists()


class TestIsAlive:
    def test_current_process_is_alive(self) -> None:
        assert is_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self) -> None:
        # Use a PID that almost certainly does not exist.
        assert is_alive(2_000_000_000) is False

    def test_zero_is_not_alive(self) -> None:
        assert is_alive(0) is False

    def test_negative_is_not_alive(self) -> None:
        assert is_alive(-1) is False


class TestIsAliveWithStart:
    def test_current_process_with_its_start_time(self) -> None:
        start_time = _proc_start_time(os.getpid())
        assert start_time is not None
        assert is_alive_with_start(os.getpid(), start_time) is True

    def test_rejects_wrong_start_time(self) -> None:
        # Live process but wrong start_time: identity mismatch.
        current = _proc_start_time(os.getpid())
        assert current is not None
        assert is_alive_with_start(os.getpid(), current + 1) is False

    def test_rejects_dead_pid(self) -> None:
        assert is_alive_with_start(2_000_000_000, 1) is False

    def test_rejects_none_start_time(self) -> None:
        # No recorded identity = stale; refuse to confirm liveness.
        assert is_alive_with_start(os.getpid(), None) is False

    def test_rejects_zero_pid(self) -> None:
        assert is_alive_with_start(0, 1) is False

    def test_rejects_negative_pid(self) -> None:
        assert is_alive_with_start(-1, 1) is False
