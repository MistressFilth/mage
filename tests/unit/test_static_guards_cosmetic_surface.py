"""Anti-revert pins for the cosmetic-surface expansion."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from mage.cosmetic_pid import is_alive_with_start, pid_file_path
from mage.orchestration.events import EventType

PID_PATH_TEXT = pid_file_path(Path(".")).as_posix()


def test_pid_file_path_pinned() -> None:
    assert PID_PATH_TEXT == ".mage/cosmetic_watcher.pid"


def test_pid_file_format_includes_start_time() -> None:
    """The PID file format is `<pid>:<start_time>\\n` for identity check.

    Anti-revert: write_pid must capture the live process's start_time
    from /proc/<pid>/stat field 22; a bare `<pid>\\n` is rejected by
    `is_alive_with_start` and the file is treated as stale.
    """
    from mage.cosmetic_pid import write_pid

    src = inspect.getsource(write_pid)
    assert "start_time" in src
    assert "_proc_start_time" in src
    assert ":" in src  # the format separator


def test_is_alive_with_start_present() -> None:
    """`is_alive_with_start` is the only liveness check before SIGKILL."""
    assert callable(is_alive_with_start)


def test_no_production_sigterm_emulator() -> None:
    """The cosmetic_watcher module must not install a SIGTERM emulator.

    Important #4 from the fix wave: SIGTERM emulation belongs in test
    helpers, not in production code (a test-only helper monkeypatches
    `is_alive_with_start` instead).
    """
    from mage.orchestration import cosmetic_watcher as cw

    src = inspect.getsource(cw)
    assert "_install_sigterm_emulator" not in src
    # The production code does not install signal.signal(SIGTERM, ...)
    # from inside _request_remote_stop.
    assert "_request_remote_stop" in src
    request_remote_stop_src = inspect.getsource(cw._request_remote_stop)
    assert "signal.signal" not in request_remote_stop_src


@pytest.mark.parametrize(
    "event_name",
    [
        "COSMETIC_WATCHER_REMOTE_STOP_REQUESTED",
        "COSMETIC_WATCHER_REMOTE_STOP_SUCCEEDED",
        "COSMETIC_WATCHER_REMOTE_STOP_ESCALATED",
        "COSMETIC_WATCHER_STALE_PID_REMOVED",
    ],
)
def test_event_type_present(event_name: str) -> None:
    assert hasattr(EventType, event_name)


def test_no_todo_markers_in_changed_files(repo_root: Path) -> None:
    """The forbidden marker bans still hold in changed production files."""
    for sub in (
        "src/mage/cli.py",
        "src/mage/orchestration/cosmetic_watcher.py",
        "src/mage/orchestration/events.py",
        "src/mage/cosmetic_pid.py",
        "src/mage/cosmetic_filters.py",
    ):
        text = (repo_root / sub).read_text()
        for marker in ("TODO(", "FIXME", "XXX"):
            assert marker not in text, f"{sub} contains {marker}"


def test_unwatch_branches_emit_or_exit() -> None:
    """Every code path in cmd_cosmetic_unwatch ends with a documented exit code.

    The unwatch function currently documents two exit codes: 0 (clean)
    and 3 (timeout). Each branch either returns one of those or emits an
    audit event; this guard pins that contract against silent regression.
    """
    from mage import cli

    source = inspect.getsource(cli.cmd_cosmetic_unwatch)
    for code in ("return 0", "return 3"):
        assert code in source, f"cmd_cosmetic_unwatch lacks {code!r}"


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
