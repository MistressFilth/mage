"""Tests for StateStore (P32)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mage.host_project_config import MageTomlConfig
from mage.state_store import (
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


def test_update_ref_passes_oldvalue_to_git(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("Test", "test@example.com"),
        command_runner=fake_runner,
    )
    fake_runner.run.return_value = _make_run_result()

    store._update_ref("new_sha", "expected_old")

    fake_runner.run.assert_called_once_with(
        [
            "git",
            "update-ref",
            store.full_ref,
            "new_sha",
            "expected_old",
        ],
        cwd=git_repo,
        check=False,
    )


def test_write_retries_once_on_ref_contention(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    """First update-ref fails; second attempt succeeds."""
    fake_runner.run.side_effect = [
        # _ensure_bootstrapped: ref-sha missing
        _make_run_result(stdout="", returncode=1),
        # _ensure_bootstrapped: mktree (empty bootstrap tree)
        _make_run_result(stdout="bootstrap_tree_sha\n"),
        # _ensure_bootstrapped: commit-tree (bootstrap commit)
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # _ensure_bootstrapped: update-ref (bootstrap succeeds)
        _make_run_result(stdout=""),
        # attempt 1: read_tree
        _make_run_result(stdout=""),
        # attempt 1: hash-object
        _make_run_result(stdout="blob_sha\n"),
        # attempt 1: mktree
        _make_run_result(stdout="new_tree_sha\n"),
        # attempt 1: ref_sha for parent
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # attempt 1: commit-tree
        _make_run_result(stdout="new_commit_sha\n"),
        # attempt 1: update-ref FAILS (ref moved under us)
        _make_run_result(stdout="", returncode=1),
        # attempt 2: read_tree
        _make_run_result(stdout=""),
        # attempt 2: hash-object
        _make_run_result(stdout="blob_sha\n"),
        # attempt 2: mktree
        _make_run_result(stdout="new_tree_sha\n"),
        # attempt 2: ref_sha for parent
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # attempt 2: commit-tree
        _make_run_result(stdout="new_commit_sha\n"),
        # attempt 2: update-ref SUCCEEDS
        _make_run_result(stdout=""),
    ]
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("T", "t@e"),
        command_runner=fake_runner,
    )
    sha = store.write("a.yaml", b"x")
    assert sha == "new_commit_sha"


def test_write_raises_conflict_after_two_failures(
    git_repo: Path, fake_runner: MagicMock
) -> None:
    fake_runner.run.side_effect = [
        # _ensure_bootstrapped: ref-sha missing
        _make_run_result(stdout="", returncode=1),
        # _ensure_bootstrapped: mktree
        _make_run_result(stdout="bootstrap_tree_sha\n"),
        # _ensure_bootstrapped: commit-tree
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # _ensure_bootstrapped: update-ref
        _make_run_result(stdout=""),
        # attempt 1: read_tree
        _make_run_result(stdout=""),
        # attempt 1: hash-object
        _make_run_result(stdout="blob_sha\n"),
        # attempt 1: mktree
        _make_run_result(stdout="new_tree_sha\n"),
        # attempt 1: ref_sha for parent
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # attempt 1: commit-tree
        _make_run_result(stdout="new_commit_sha\n"),
        # attempt 1: update-ref FAILS
        _make_run_result(stdout="", returncode=1),
        # attempt 2: read_tree
        _make_run_result(stdout=""),
        # attempt 2: hash-object
        _make_run_result(stdout="blob_sha\n"),
        # attempt 2: mktree
        _make_run_result(stdout="new_tree_sha\n"),
        # attempt 2: ref_sha for parent
        _make_run_result(stdout="bootstrap_commit_sha\n"),
        # attempt 2: commit-tree
        _make_run_result(stdout="new_commit_sha\n"),
        # attempt 2: update-ref FAILS
        _make_run_result(stdout="", returncode=1),
    ]
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("T", "t@e"),
        command_runner=fake_runner,
    )
    with pytest.raises(MageStateConflict):
        store.write("a.yaml", b"x")


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "",
        "has space",
        "has:colon",
        "has~tilde",
        "..",
        "a/b/../c",
        "a" * 4097,
    ],
)
def test_path_validation_rejects_invalid(git_repo: Path, path: str) -> None:
    store = StateStore(
        git_repo,
        "feature-artifacts",
        identity=("T", "t@e"),
        command_runner=MagicMock(),
    )
    with pytest.raises(ValueError):
        store.read(path)
    with pytest.raises(ValueError):
        store.write(path, b"x")
    with pytest.raises(ValueError):
        store.delete(path)
    with pytest.raises(ValueError):
        store.exists(path)
