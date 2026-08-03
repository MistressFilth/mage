"""Spawn a real `mage cosmetic watch` and stop it via `mage cosmetic unwatch`."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from mage.cosmetic_pid import pid_file_path, read_pid


def _mage() -> list[str]:
    """Return the command list to invoke the `mage` console script."""
    binary = shutil.which("mage")
    if binary is None:
        pytest.fail("mage console script not found on PATH")
    return [binary]


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
            if read_pid(tmp_path) is not None:
                break
            time.sleep(0.05)
        else:
            pytest.fail("PID file did not appear within 5s")

        parsed = read_pid(tmp_path)
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
        assert not pid_file_path(tmp_path).exists()
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
