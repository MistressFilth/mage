"""Tests for state_migration (P32)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mage.host_project_config import MageTomlConfig
from mage.state_migration import (
    MageStateMigrationError,
    MageStateMigrationUnsupported,
    maybe_migrate,
    restore_from_backup,
)
from mage.state_store import state_store_for


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
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


def _populate_legacy_state(project_root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = project_root / ".mage" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_maybe_migrate_noop_when_no_legacy_dir(git_repo: Path) -> None:
    store = state_store_for(git_repo, MageTomlConfig())
    assert maybe_migrate(git_repo, store) is False


def test_maybe_migrate_copies_files_to_orphan_branch(git_repo: Path) -> None:
    _populate_legacy_state(
        git_repo,
        {
            "inspect/feature_a/0.yaml": "finding: yes\n",
            "state/pipeline-state.yaml": "stage: inscribe\n",
        },
    )
    store = state_store_for(git_repo, MageTomlConfig())
    assert maybe_migrate(git_repo, store) is True
    assert store.read("inspect/feature_a/0.yaml") == b"finding: yes\n"
    assert store.read("state/pipeline-state.yaml") == b"stage: inscribe\n"


def test_maybe_migrate_renames_legacy_to_backup(git_repo: Path) -> None:
    _populate_legacy_state(git_repo, {"foo.yaml": "bar\n"})
    store = state_store_for(git_repo, MageTomlConfig())
    maybe_migrate(git_repo, store)
    backups = list(git_repo.glob(".mage.bak.*"))
    assert len(backups) == 1
    assert any(p.name == "foo.yaml" for p in backups[0].rglob("*"))


def test_maybe_migrate_idempotent(git_repo: Path) -> None:
    _populate_legacy_state(git_repo, {"a.yaml": "1\n"})
    store = state_store_for(git_repo, MageTomlConfig())
    assert maybe_migrate(git_repo, store) is True
    assert maybe_migrate(git_repo, store) is False  # second call no-ops


def test_maybe_migrate_rejects_unsupported_extension(git_repo: Path) -> None:
    _populate_legacy_state(git_repo, {"foo.bin": "binary\n"})
    store = state_store_for(git_repo, MageTomlConfig())
    with pytest.raises(MageStateMigrationUnsupported):
        maybe_migrate(git_repo, store)


def test_maybe_migrate_rejects_symlink(git_repo: Path) -> None:
    legacy = git_repo / ".mage"
    legacy.mkdir()
    target = git_repo / "target.txt"
    target.write_text("hello")
    (legacy / "link.yaml").symlink_to(target)
    store = state_store_for(git_repo, MageTomlConfig())
    with pytest.raises(MageStateMigrationUnsupported):
        maybe_migrate(git_repo, store)


def test_restore_from_backup_roundtrip(git_repo: Path) -> None:
    _populate_legacy_state(git_repo, {"a.yaml": "1\n", "b.yaml": "2\n"})
    store = state_store_for(git_repo, MageTomlConfig())
    maybe_migrate(git_repo, store)
    backups = list(git_repo.glob(".mage.bak.*"))
    assert len(backups) == 1
    ts = backups[0].name.removeprefix(".mage.bak.")
    new_sha = restore_from_backup(git_repo, store, timestamp=ts)
    assert isinstance(new_sha, str) and len(new_sha) > 0
    # Verify content survived restore round-trip.
    assert store.read("a.yaml") == b"1\n"
    assert store.read("b.yaml") == b"2\n"


def test_restore_missing_backup_raises(git_repo: Path) -> None:
    store = state_store_for(git_repo, MageTomlConfig())
    with pytest.raises((FileNotFoundError, MageStateMigrationError)):
        restore_from_backup(git_repo, store, timestamp="99999999T999999")
