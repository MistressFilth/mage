"""Spawn a real `mage cosmetic watch` and stop it via `mage cosmetic unwatch`.

P32 task 13: the PID file lives on the mage orphan branch at
``cosmetic_watcher.pid`` rather than at ``<project_dir>/.mage/cosmetic_watcher.pid``.
This test reads the PID via the StateStore-backed helpers so the e2e
flow exercises the same path as production.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mage.cosmetic_pid import (
    pid_file_via_state_store,
    read_pid_via_state_store,
)
from mage.state_store import StateStore


def _mage() -> list[str]:
    """Return the command list to invoke the `mage` console script."""
    binary = shutil.which("mage")
    if binary is None:
        pytest.fail("mage console script not found on PATH")
    return [binary]


def _store(project_dir: Path) -> StateStore:
    """Build a StateStore anchored at ``project_dir`` (P32 task 13)."""
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
    return StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows spawns an intermediate launcher process; watch_proc.pid doesn't match the PID recorded inside the actual mage subprocess",
)
def test_watch_then_unwatch(tmp_path: Path) -> None:
    mapping_yaml = """
schema_version: 2
project_id: e2e
base_bids: []
inspect_journal: {}
feature_cosmetic_queue: []
feature_status: pending
"""
    (tmp_path / "mapping.yaml").write_text(mapping_yaml)
    state_store = _store(tmp_path)
    pid_ref = pid_file_via_state_store(state_store)

    watch_proc = subprocess.Popen(
        [
            *_mage(),
            "cosmetic",
            "watch",
            "--project-dir",
            str(tmp_path),
            "--poll-interval-ms",
            "50",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if read_pid_via_state_store(state_store) is not None:
                break
            time.sleep(0.05)
        else:
            pytest.fail("PID file did not appear within 5s")

        parsed = read_pid_via_state_store(state_store)
        assert parsed is not None
        recorded_pid, recorded_start_time = parsed
        assert recorded_pid == watch_proc.pid
        # start_time is captured from /proc/<pid>/stat for identity check.
        assert recorded_start_time is not None and recorded_start_time > 0

        result = subprocess.run(
            [
                *_mage(),
                "cosmetic",
                "unwatch",
                "--project-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        assert result.returncode == 0
        # Orphan branch: the PID entry has been removed.
        assert not state_store.read(pid_ref)
        assert watch_proc.wait(timeout=10.0) == 0

        events = [
            json.loads(line)
            for line in (tmp_path / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        event_types = [event["event_type"] for event in events]
        assert "cosmetic_watcher_remote_stop_requested" in event_types
        assert "cosmetic_watcher_remote_stop_succeeded" in event_types
        assert "cosmetic_watcher_stopped" in event_types
    finally:
        if watch_proc.poll() is None:
            watch_proc.terminate()
            try:
                watch_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                watch_proc.kill()
