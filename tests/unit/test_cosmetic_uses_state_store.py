"""Cosmetic + approval + host_config I/O uses StateStore (P32 task 13)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mage.state_store import StateStore


def _init_git_repo(project_dir: Path) -> None:
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


def _store(project_dir: Path) -> StateStore:
    return StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))


def test_approval_pending_path(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    store = _store(tmp_path)
    store.write("approval_pending.json", b'{"feature_id": "abc"}')
    assert store.read("approval_pending.json") == b'{"feature_id": "abc"}'


def test_pid_file_path(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    store = _store(tmp_path)
    store.write("cosmetic_watcher.pid", b"1234:9999\n")
    assert store.read("cosmetic_watcher.pid") == b"1234:9999\n"


def test_cosmetic_applied_path(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    store = _store(tmp_path)
    store.write("cosmetic/cosmetic_applied.yaml", b"applied: {}\n")
    assert store.read("cosmetic/cosmetic_applied.yaml") == b"applied: {}\n"


def test_host_config_path(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    store = _store(tmp_path)
    store.write("host_config.yaml", b"max_iterations: 3\n")
    assert store.read("host_config.yaml") == b"max_iterations: 3\n"
