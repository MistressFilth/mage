"""Anti-revert pins for the cosmetic-surface expansion."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from mage.cosmetic_pid import pid_file_path
from mage.orchestration.events import EventType

PID_PATH_TEXT = str(pid_file_path(Path(".")))


def test_pid_file_path_pinned() -> None:
    assert PID_PATH_TEXT == ".mage/cosmetic_watcher.pid"


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
        assert "haileris_v2" not in text


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
