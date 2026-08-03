"""Watcher PID write/remove contracts around run()/stop()."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mage.cosmetic_pid import pid_file_path, read_pid
from mage.orchestration.cosmetic_watcher import MappingArtifactWatcher
from mage.orchestration.events import EventsLog


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".mage").mkdir()
    return tmp_path


async def _drain_to_stale(watcher: MappingArtifactWatcher) -> None:
    """Wait briefly so the watcher writes its PID file before stop()."""
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_run_writes_pid_file(project_dir: Path) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(project_dir, events_log=EventsLog(log))
    # Run only until stop is called.
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)  # let run() write the PID file
    parsed = read_pid(project_dir)
    assert parsed is not None
    pid, start_time = parsed
    assert pid == __import__("os").getpid()
    # start_time must be recorded for identity verification.
    assert start_time is not None and start_time > 0
    watcher.stop()
    await task


@pytest.mark.asyncio
async def test_stop_removes_pid_file(project_dir: Path) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(project_dir, events_log=EventsLog(log))
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    assert pid_file_path(project_dir).exists()
    watcher.stop()
    await task
    assert not pid_file_path(project_dir).exists()


@pytest.mark.asyncio
async def test_started_event_carries_pid_payload(project_dir: Path) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(project_dir, events_log=EventsLog(log))
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    watcher.stop()
    await task
    lines = log.read_text().splitlines()
    started = next(line for line in lines if "cosmetic_watcher_started" in line)
    import json

    payload = json.loads(started)["payload"]
    assert payload["pid"] == __import__("os").getpid()
    assert payload["pid_file_path"].endswith("cosmetic_watcher.pid")


@pytest.mark.asyncio
async def test_stopped_event_carries_pid_file_removed(project_dir: Path) -> None:
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(project_dir, events_log=EventsLog(log))
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
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If `.mage/` is not writable, run() must still start.

    The PID file is a coordination convenience; not a precondition.
    """
    from mage.orchestration import cosmetic_watcher as cw

    def _boom(*_args, **_kwargs):
        raise OSError("readonly")

    monkeypatch.setattr(cw, "write_pid", _boom)
    log = project_dir / "events.jsonl"
    log.touch()
    watcher = MappingArtifactWatcher(project_dir, events_log=EventsLog(log))
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    watcher.stop()
    await task
    # Watcher still ran.
