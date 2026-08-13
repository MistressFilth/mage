"""End-to-end test: legacy .mage/ migrates to orphan branch on first access (P32)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mage.host_project_config import MageTomlConfig
from mage.state_migration import maybe_migrate
from mage.state_store import StateStore, state_store_for
from tests.conftest import init_git_repo


def _bare_store(project_root: Path) -> StateStore:
    """A StateStore that does NOT auto-migrate.

    ``state_store_for`` wires :func:`maybe_migrate` as a side effect;
    the explicit-migration assertions below exercise the helper on its
    own and need a side-effect-free harness.
    """
    return StateStore(
        project_root,
        "feature-artifacts",
        identity=("T", "t@e"),
    )


def test_legacy_dot_mage_migrates(tmp_path: Path) -> None:
    """A legacy `.mage/` tree migrates to the orphan branch on first read.

    On ``maybe_migrate``:

    - Each `.mage/<rel>` file is written to
      ``refs/mage/feature-artifacts:<rel>``.
    - The legacy ``.mage/`` directory is renamed to
      ``.mage.bak.<YYYYMMDDTHHMMSS>/`` (atomic OS rename, no copy).
    - A ``_meta/.migrated`` marker is written to the orphan branch to
      guard against re-running the migration.
    """
    init_git_repo(tmp_path)
    legacy = tmp_path / ".mage" / "inspect" / "fid"
    legacy.mkdir(parents=True)
    (legacy / "0.yaml").write_bytes(b"finding: yes\n")

    store = _bare_store(tmp_path)
    assert maybe_migrate(tmp_path, store) is True

    # Orphan branch carries the migrated content.
    out = subprocess.run(
        ["git", "ls-tree", "-r", "refs/mage/feature-artifacts"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, f"git ls-tree on orphan branch failed: {out.stderr!r}"
    assert "inspect/fid/0.yaml" in out.stdout

    # The legacy tree is renamed to a timestamped backup exactly once.
    assert not (tmp_path / ".mage").exists()
    backups = list(tmp_path.glob(".mage.bak.*"))
    assert len(backups) == 1
    assert any(p.name == "0.yaml" for p in backups[0].rglob("*"))

    # The migration marker is recorded on the orphan branch.
    assert store.exists("_meta/.migrated")


def test_legacy_migration_is_idempotent(tmp_path: Path) -> None:
    """Re-running ``maybe_migrate`` after a successful migration is a no-op."""
    init_git_repo(tmp_path)
    legacy = tmp_path / ".mage"
    legacy.mkdir()
    (legacy / "foo.yaml").write_bytes(b"bar\n")

    store = _bare_store(tmp_path)
    assert maybe_migrate(tmp_path, store) is True
    assert maybe_migrate(tmp_path, store) is False
    # Still exactly one backup directory.
    backups = list(tmp_path.glob(".mage.bak.*"))
    assert len(backups) == 1


def test_state_store_for_triggers_auto_migration(tmp_path: Path) -> None:
    """Fix 1: ``state_store_for`` now wires ``maybe_migrate``.

    Setting up a legacy ``.mage/`` tree then calling ``state_store_for``
    once should rename it to ``.mage.bak.<ts>/`` without the caller
    invoking ``maybe_migrate`` explicitly.
    """
    init_git_repo(tmp_path)
    legacy = tmp_path / ".mage"
    legacy.mkdir()
    (legacy / "foo.yaml").write_bytes(b"bar\n")

    state_store_for(tmp_path, MageTomlConfig())
    backups = list(tmp_path.glob(".mage.bak.*"))
    assert len(backups) == 1
    assert not (tmp_path / ".mage").exists()
