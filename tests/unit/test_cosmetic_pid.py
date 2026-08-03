"""PID file lifecycle helper tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mage.cosmetic_pid import (
    is_alive,
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
    def test_writes_pid_with_newline(self, mage_dir: Path) -> None:
        path = write_pid(mage_dir, 12345)
        assert path == mage_dir / ".mage" / "cosmetic_watcher.pid"
        assert path.read_text() == "12345\n"

    def test_writes_to_nested_path(self, tmp_path: Path) -> None:
        # write_pid creates .mage/ if missing
        path = write_pid(tmp_path, 9999)
        assert path.exists()
        assert (tmp_path / ".mage").is_dir()


class TestRead:
    def test_returns_none_when_missing(self, mage_dir: Path) -> None:
        assert read_pid(mage_dir) is None

    def test_returns_int_when_present(self, mage_dir: Path) -> None:
        write_pid(mage_dir, 4242)
        assert read_pid(mage_dir) == 4242

    def test_returns_none_on_garbage(self, mage_dir: Path) -> None:
        path = pid_file_path(mage_dir)
        path.write_text("not-a-pid\n")
        assert read_pid(mage_dir) is None


class TestRemove:
    def test_returns_false_when_missing(self, mage_dir: Path) -> None:
        assert remove_pid(mage_dir) is False

    def test_removes_when_present(self, mage_dir: Path) -> None:
        write_pid(mage_dir, 1)
        assert remove_pid(mage_dir) is True
        assert not pid_file_path(mage_dir).exists()


class TestIsAlive:
    def test_current_process_is_alive(self) -> None:
        import os

        assert is_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self) -> None:
        # Use a PID that almost certainly does not exist.
        assert is_alive(2_000_000_000) is False

    def test_zero_is_not_alive(self) -> None:
        assert is_alive(0) is False

    def test_negative_is_not_alive(self) -> None:
        assert is_alive(-1) is False
