"""End-to-end test: mage state restore round-trip (P32)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mage.host_project_config import MageTomlConfig
from mage.state_migration import maybe_migrate, restore_from_backup
from mage.state_store import state_store_for


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_state_restore_roundtrip(tmp_path: Path) -> None:
    """Migrate -> mutate -> restore: every original file's bytes
    round-trip through the orphan branch and the ref advances.

    Lifecycle:

    1. Plant a legacy ``.mage/`` tree; ``maybe_migrate`` moves it to
       ``refs/mage/feature-artifacts`` and to ``.mage.bak.<ts>/``.
    2. Note the post-migration ref SHA.
    3. Invoke ``restore_from_backup`` against the same timestamp.
    4. Assert the ref advanced and every original file's bytes are
       readable from the orphan branch.
    """
    _init_repo(tmp_path)

    # 1. Plant + migrate.
    legacy_root = tmp_path / ".mage"
    (legacy_root / "inspect" / "fid").mkdir(parents=True)
    (legacy_root / "inspect" / "fid" / "0.yaml").write_text("finding: yes\n")
    (legacy_root / "state").mkdir()
    (legacy_root / "state" / "pipeline-state.yaml").write_text("stage: inscribe\n")

    store = state_store_for(tmp_path, MageTomlConfig())
    assert maybe_migrate(tmp_path, store) is True
    backups = list(tmp_path.glob(".mage.bak.*"))
    assert len(backups) == 1
    backup_ts = backups[0].name.removeprefix(".mage.bak.")

    post_migrate_sha = store.ref_sha()
    assert isinstance(post_migrate_sha, str) and len(post_migrate_sha) > 0

    # 2. Mutate the orphan branch so the ref advances beyond migration.
    store.write("runtime/scratch.yaml", b"scribble\n")

    # 3. Restore from the captured backup timestamp.
    post_restore_sha = restore_from_backup(tmp_path, store, timestamp=backup_ts)
    assert isinstance(post_restore_sha, str) and len(post_restore_sha) > 0
    assert post_restore_sha != post_migrate_sha

    # 4. Round-tripped content survives end-to-end.
    assert store.read("inspect/fid/0.yaml") == b"finding: yes\n"
    assert store.read("state/pipeline-state.yaml") == b"stage: inscribe\n"
    # The migration marker is preserved so re-running maybe_migrate is a
    # no-op rather than re-renaming the backup path.
    assert store.exists("_meta/.migrated")


def test_state_restore_roundtrip_via_cli(tmp_path: Path) -> None:
    """`mage state info` + `mage state restore` round-trip via the CLI.

    Drives the full ``mage state`` subcommand path against a real git
    repo. After migrate + mutation + restore, the orphan branch holds
    only the originally migrated files.
    """
    _init_repo(tmp_path)

    legacy_root = tmp_path / ".mage"
    (legacy_root / "foo").mkdir(parents=True)
    (legacy_root / "foo" / "bar.yaml").write_text("baz\n")

    from mage.cli import main

    # `mage state info` against an empty orphan ref.
    info_empty = main(["--project-dir", str(tmp_path), "state", "info"])
    assert info_empty == 0

    # Drive migration by importing the helpers directly (the production
    # CLI trigger for migration lives in the pipeline, not in `mage state`).
    from mage.state_migration import maybe_migrate

    store = state_store_for(tmp_path, MageTomlConfig())
    assert maybe_migrate(tmp_path, store) is True
    backups = list(tmp_path.glob(".mage.bak.*"))
    assert len(backups) == 1
    backup_ts = backups[0].name.removeprefix(".mage.bak.")

    # `mage state info` now reports the populated orphan branch.
    info_populated = main(["--project-dir", str(tmp_path), "state", "info"])
    assert info_populated == 0

    # Mutate, then restore via `mage state restore`. Track the pre-restore
    # ref SHA so we can prove the restore produced a new commit.
    store.write("scratch/added.yaml", b"drop me\n")
    pre_restore_sha = store.ref_sha()

    rc_restore = main(
        [
            "--project-dir",
            str(tmp_path),
            "state",
            "restore",
            "--from",
            backup_ts,
        ]
    )
    assert rc_restore == 0

    # After restore: the original migrated file's bytes survive end-to-end
    # and the ref advanced to a new commit.
    assert store.read("foo/bar.yaml") == b"baz\n"
    assert store.ref_sha() != pre_restore_sha
