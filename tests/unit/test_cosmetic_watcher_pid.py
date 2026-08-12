"""Watcher PID write/remove contracts around run()/stop().

P32 task 13: the watcher PID file lives on the mage orphan branch at
``cosmetic_watcher.pid`` rather than at ``<project_dir>/.mage/cosmetic_watcher.pid``.
These tests inject a ``StateStore`` and verify the watcher reads / writes /
removes the orphan-branch entry exactly as the working-tree file contracts
used to.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from mage.cosmetic_pid import (
    pid_file_via_state_store,
    read_pid_via_state_store,
)
from mage.orchestration.cosmetic_watcher import MappingArtifactWatcher
from mage.orchestration.events import EventsLog
from mage.state_store import StateStore


def _init_git_repo(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "project").mkdir()
    (tmp_path / ".mage").mkdir()
    _init_git_repo(tmp_path)
    return tmp_path / "project"


@pytest.fixture
def state_store(tmp_path: Path) -> StateStore:
    """A StateStore backed by ``tmp_path``'s git repo (separate from project_dir)."""
    return StateStore(tmp_path, "feature-artifacts", identity=("T", "t@e"))


async def _drain_to_stale(watcher: MappingArtifactWatcher) -> None:
    """Wait briefly so the watcher writes its PID file before stop()."""
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_run_writes_pid_file(project_dir: Path, state_store: StateStore) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(
        project_dir, events_log=EventsLog(log), state_store=state_store
    )
    # Run only until stop is called.
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)  # let run() write the PID file
    parsed = read_pid_via_state_store(state_store)
    assert parsed is not None
    pid, start_time = parsed
    assert pid == __import__("os").getpid()
    # start_time must be recorded for identity verification.
    assert start_time is not None and start_time > 0
    watcher.stop()
    await task


@pytest.mark.asyncio
async def test_stop_removes_pid_file(
    project_dir: Path, state_store: StateStore
) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(
        project_dir, events_log=EventsLog(log), state_store=state_store
    )
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    assert state_store.read(pid_file_via_state_store(state_store))
    watcher.stop()
    await task
    assert not state_store.read(pid_file_via_state_store(state_store))


@pytest.mark.asyncio
async def test_started_event_carries_pid_payload(
    project_dir: Path, state_store: StateStore
) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(
        project_dir, events_log=EventsLog(log), state_store=state_store
    )
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    watcher.stop()
    await task
    lines = log.read_text().splitlines()
    started = next(line for line in lines if "cosmetic_watcher_started" in line)
    import json

    payload = json.loads(started)["payload"]
    assert payload["pid"] == __import__("os").getpid()
    assert payload["pid_file_path"] == "cosmetic_watcher.pid"


@pytest.mark.asyncio
async def test_stopped_event_carries_pid_file_removed(
    project_dir: Path, state_store: StateStore
) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(
        project_dir, events_log=EventsLog(log), state_store=state_store
    )
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    watcher.stop()
    await task
    lines = log.read_text().splitlines()
    stopped = next(line for line in lines if "cosmetic_watcher_stopped" in line)
    import json

    payload = json.loads(stopped)["payload"]
    assert payload["pid_file_removed"] is True


@pytest.mark.asyncio
async def test_run_does_not_block_when_pid_write_fails(
    project_dir: Path, state_store: StateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If PID write raises, ``run()`` must still start.

    The PID file is a coordination convenience; not a precondition. P32
    writes live on the orphan branch; this stub fails the underlying
    ``write_pid_via_state_store`` call so we exercise the failure path
    inside ``_pid_info_via_store`` (which catches OSError).
    """
    from mage import cosmetic_pid as cp

    def _boom(*_args, **_kwargs):
        raise OSError("readonly")

    with patch.object(cp, "write_pid_via_state_store", _boom):
        log = project_dir / "events.jsonl"
        log.touch()
        watcher = MappingArtifactWatcher(
            project_dir, events_log=EventsLog(log), state_store=state_store
        )
        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.05)
        watcher.stop()
        await task
    # Watcher still ran.
