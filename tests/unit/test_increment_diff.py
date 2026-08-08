"""Tests for mage.orchestration.increment_diff — module-direct, no fixtures.

RealizeStage integration tests live in tests/unit/test_realize_stage.py.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from mage.orchestration.increment_diff import (
    compute_unified_diff,
    snapshot_tree,
)


def _make_git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo with one tracked, committed file. Return cwd path."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("alpha\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_snapshot_files_records_existence_and_content(tmp_path: Path) -> None:
    # Use binary mode so line endings are preserved across platforms
    # (text mode on Windows would translate "\n" to "\r\n").
    (tmp_path / "present.txt").write_bytes(b"hi\n")
    snap = snapshot_tree(tmp_path)
    assert "present.txt" in snap
    s = snap["present.txt"]
    assert s.exists is True
    assert s.content == b"hi\n"
    assert s.mode is not None
    # Compare against the actual file's mode rather than pinning a literal
    # (Linux reports 0o644, Windows reports 0o666 — both are valid creation
    # defaults; we only care that the snapshot reflects the real mode).
    assert s.mode == stat.S_IMODE((tmp_path / "present.txt").stat().st_mode)


def test_snapshot_tree_excludes_dotgit_directory(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    (tmp_path / ".git" / "extra").write_text("ignored")
    snap = snapshot_tree(tmp_path)
    assert all(not k.startswith(".git/") for k in snap)


def test_compute_unified_diff_addition(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    pre = snapshot_tree(tmp_path)
    (tmp_path / "new.txt").write_text("brand new\n")
    diff, warnings = compute_unified_diff(tmp_path, ["new.txt"], pre)
    assert warnings == []
    assert "new.txt" in diff
    assert "+brand new" in diff


def test_compute_unified_diff_deletion(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    pre = snapshot_tree(tmp_path)
    (tmp_path / "a.txt").unlink()
    diff, warnings = compute_unified_diff(tmp_path, ["a.txt"], pre)
    assert warnings == []
    assert "-alpha" in diff


def test_compute_unified_diff_modification(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    pre = snapshot_tree(tmp_path)
    (tmp_path / "a.txt").write_text("alpha\nbeta\n")
    diff, warnings = compute_unified_diff(tmp_path, ["a.txt"], pre)
    assert warnings == []
    assert "+beta" in diff
    assert "a.txt" in diff


def test_compute_unified_diff_both_missing_returns_warning(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    pre = snapshot_tree(tmp_path)
    diff, warnings = compute_unified_diff(tmp_path, ["never_existed.txt"], pre)
    assert diff == ""
    assert len(warnings) == 1
    assert "never_existed.txt" in warnings[0]


def test_compute_unified_diff_binary_marker(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02binary\x00")
    pre = snapshot_tree(tmp_path)
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02changed\x00")
    diff, warnings = compute_unified_diff(tmp_path, ["blob.bin"], pre)
    assert warnings == []
    assert "Binary files" in diff
    assert "blob.bin" in diff


def test_compute_unified_diff_path_traversal_rejected(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    pre = snapshot_tree(tmp_path)
    diff, warnings = compute_unified_diff(tmp_path, ["../escape.txt"], pre)
    assert diff == ""
    assert len(warnings) == 1
    assert "escape.txt" in warnings[0]


def test_compute_unified_diff_empty_paths_returns_empty(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    pre = snapshot_tree(tmp_path)
    diff, warnings = compute_unified_diff(tmp_path, [], pre)
    assert diff == ""
    assert warnings == []
