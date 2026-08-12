"""One-shot migration from legacy `.mage/` to orphan-branch state (P32)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from mage.state_store import StateStore

__all__ = [
    "MageStateMigrationContention",
    "MageStateMigrationError",
    "MageStateMigrationReadFailed",
    "MageStateMigrationUnsupported",
    "maybe_migrate",
    "restore_from_backup",
]

_LEGACY_DIR = Path(".mage")
_BACKUP_PREFIX = ".mage.bak."
_TIMESTAMP_FMT = "%Y%m%dT%H%M%S"
_ALLOWED_EXTENSIONS = {".yaml", ".json", ".txt", ".pid"}
_MIGRATION_MARKER = "_meta/.migrated"


class MageStateMigrationError(RuntimeError):
    """Base class for state migration failures."""


class MageStateMigrationUnsupported(MageStateMigrationError):
    """A file under `.mage/` has an unsupported extension or is a symlink."""


class MageStateMigrationContention(MageStateMigrationError):
    """Two concurrent migrations in the same second collided."""


class MageStateMigrationReadFailed(MageStateMigrationError):
    """Reading a legacy state file failed."""


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
    ) -> Any: ...


def _now_timestamp(now: datetime | None = None) -> str:
    t = now or datetime.now(UTC)
    return t.strftime(_TIMESTAMP_FMT)


def _legacy_backup_path(project_root: Path, ts: str) -> Path:
    return project_root / f"{_BACKUP_PREFIX}{ts}"


def _is_migrated_marker_present(state_store: StateStore) -> bool:
    return state_store.exists(_MIGRATION_MARKER)


def _walk_legacy_files(project_root: Path) -> list[Path]:
    legacy = project_root / _LEGACY_DIR
    if not legacy.exists():
        return []
    files: list[Path] = []
    for path in legacy.rglob("*"):
        if path.is_symlink():
            raise MageStateMigrationUnsupported(f"symlink under .mage/: {path}")
        if not path.is_file():
            continue
        ext = path.suffix
        if ext not in _ALLOWED_EXTENSIONS:
            raise MageStateMigrationUnsupported(
                f"unsupported extension {ext!r} for {path}; "
                f"allowed: {sorted(_ALLOWED_EXTENSIONS)}"
            )
        files.append(path)
    return files


def maybe_migrate(
    project_root: Path,
    state_store: StateStore,
    *,
    now: datetime | None = None,
    command_runner: CommandRunner | None = None,
) -> bool:
    """One-shot migration. Returns True if migration ran, False if no-op.

    Pre-conditions: project_root contains a git repo.
    """
    del command_runner  # Reserved for the restore implementation in Task 6.
    legacy = project_root / _LEGACY_DIR
    if not legacy.exists():
        return False
    if _is_migrated_marker_present(state_store):
        return False
    files = _walk_legacy_files(project_root)
    for path in files:
        rel = str(path.relative_to(legacy)).replace(os.sep, "/")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise MageStateMigrationReadFailed(f"failed to read {path}: {exc}") from exc
        state_store.write(rel, data)
    state_store.write(_MIGRATION_MARKER, b"")
    ts = _now_timestamp(now)
    backup = _legacy_backup_path(project_root, ts)
    try:
        os.rename(legacy, backup)
    except FileExistsError as exc:
        raise MageStateMigrationContention(
            f"backup path {backup} already exists; another migration ran in the same second"
        ) from exc
    return True


def restore_from_backup(
    project_root: Path,
    state_store: StateStore,
    *,
    timestamp: str | None = None,
) -> str:
    """Inverse of maybe_migrate. Reads `.mage.bak.<ts>/` and writes into a
    fresh orphan-branch commit, then atomically swaps the ref.
    """
    raise NotImplementedError("Task 6 implements restore_from_backup")
