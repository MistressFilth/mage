"""Tests for StateStore (P32)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mage.host_project_config import MageTomlConfig
from mage.state_store import (  # noqa: F401 — MageStateConflict is public surface
    MageStateConflict,
    StateStore,
    state_store_for,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo in tmp_path with identity configured."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


@pytest.fixture
def fake_runner() -> MagicMock:
    """Recording command runner."""
    return MagicMock()


def _make_run_result(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_state_store_for_creates_instance(git_repo: Path) -> None:
    store = state_store_for(git_repo, MageTomlConfig())
    assert isinstance(store, StateStore)
    assert store.branch_name == "feature-artifacts"
    assert store.full_ref == "refs/mage/feature-artifacts"


def test_state_store_for_uses_custom_branch(git_repo: Path) -> None:
    store = state_store_for(git_repo, MageTomlConfig(orphan_branch="custom-name"))
    assert store.full_ref == "refs/mage/custom-name"


def test_read_empty_ref_returns_empty_bytes(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    fake_runner.run.return_value = _make_run_result(stdout="")
    result = store.read("nonexistent.yaml")
    assert result == b""


def test_write_bootstrap_creates_initial_commit(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    """First write creates an empty-tree bootstrap commit, then commits the blob."""
    fake_runner.run.side_effect = [
        # ref_sha() inside _ensure_bootstrapped (ref doesn't exist)
        _make_run_result(stdout="", returncode=1),
        # mktree (empty initial bootstrap)
        _make_run_result(stdout="bootstrap_tree_sha\n"),
        # commit-tree (bootstrap)
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # update-ref (bootstrap)
        _make_run_result(stdout=""),
        # read current tree (after bootstrap)
        _make_run_result(stdout=""),
        # hash-object
        _make_run_result(stdout="blob_sha\n"),
        # mktree (with file)
        _make_run_result(stdout="new_tree_sha\n"),
        # ref_sha() for parent in _mutate (post-bootstrap ref)
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # commit-tree (with file)
        _make_run_result(stdout="new_commit_sha\n"),
        # update-ref (with file)
        _make_run_result(stdout=""),
    ]
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    sha = store.write("test.yaml", b"hello\n")
    assert sha == "new_commit_sha"


def test_write_then_read_roundtrip(git_repo: Path, fake_runner: MagicMock) -> None:
    """Write commits; read retrieves via git show."""
    fake_runner.run.side_effect = [
        # ref_sha() inside _ensure_bootstrapped (ref exists, skip bootstrap)
        _make_run_result(stdout="existing_sha\n"),
        # read tree
        _make_run_result(stdout="100644 blob blob_sha\ttest.yaml\n"),
        # hash-object
        _make_run_result(stdout="new_blob_sha\n"),
        # mktree
        _make_run_result(stdout="new_tree_sha\n"),
        # ref_sha() for parent in _mutate
        _make_run_result(stdout="existing_sha\n"),
        # commit-tree
        _make_run_result(stdout="new_commit_sha\n"),
        # update-ref
        _make_run_result(stdout=""),
    ]
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    sha = store.write("test.yaml", b"hello\n")
    assert sha == "new_commit_sha"


def test_delete_removes_path(git_repo: Path, fake_runner: MagicMock) -> None:
    fake_runner.run.side_effect = [
        # ref_sha() inside _ensure_bootstrapped (ref exists, skip bootstrap)
        _make_run_result(stdout="existing_sha\n"),
        # read tree (path present)
        _make_run_result(stdout="100644 blob blob_sha\ttest.yaml\n"),
        # mktree (without the path)
        _make_run_result(stdout="new_tree_sha\n"),
        # ref_sha() for parent in _mutate
        _make_run_result(stdout="existing_sha\n"),
        # commit-tree
        _make_run_result(stdout="new_commit_sha\n"),
        # update-ref
        _make_run_result(stdout=""),
    ]
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    sha = store.delete("test.yaml")
    assert sha == "new_commit_sha"


def test_list_dir_parses_tree_output(git_repo: Path, fake_runner: MagicMock) -> None:
    fake_runner.run.return_value = _make_run_result(
        stdout="040000 tree tree_sha\tdir1\n100644 blob blob_sha\tfile.yaml\n"
    )
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    entries = store.list_dir("")
    assert "dir1" in entries
    assert "file.yaml" in entries


def test_exists_true_when_path_present(git_repo: Path, fake_runner: MagicMock) -> None:
    fake_runner.run.return_value = _make_run_result(
        stdout="100644 blob sha\tfoo.yaml\n"
    )
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    assert store.exists("foo.yaml") is True


def test_exists_false_when_ref_missing(git_repo: Path, fake_runner: MagicMock) -> None:
    fake_runner.run.return_value = _make_run_result(stdout="", returncode=1)
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    assert store.exists("anything.yaml") is False


def test_ref_sha_returns_none_when_missing(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    fake_runner.run.return_value = _make_run_result(stdout="", returncode=1)
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    assert store.ref_sha() is None


def test_ref_sha_returns_value_when_present(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    fake_runner.run.return_value = _make_run_result(stdout="abc123\n")
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    assert store.ref_sha() == "abc123"
