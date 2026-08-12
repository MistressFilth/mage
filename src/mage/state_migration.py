"""One-shot migration from legacy `.mage/` to orphan-branch state (P32)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from mage.orchestration.events import Event, EventsLog, EventType
from mage.state_store import (
    MIGRATION_MARKER as _MARKER,
)
from mage.state_store import (
    StateStore,
)
from mage.state_store import (
    set_events_log as _set_state_store_events_log,
)

__all__ = [
    "MageStateMigrationContention",
    "MageStateMigrationError",
    "MageStateMigrationReadFailed",
    "MageStateMigrationUnsupported",
    "maybe_migrate",
    "restore_from_backup",
    "set_events_log",
]

_LEGACY_DIR = Path(".mage")
_BACKUP_PREFIX = ".mage.bak."
_TIMESTAMP_FMT = "%Y%m%dT%H%M%S"
_ALLOWED_EXTENSIONS = {".yaml", ".json", ".txt", ".pid"}
# Re-export of the canonical marker path from mage.state_store keeps the
# single source of truth; the previous duplicate literal here drifted.
_MIGRATION_MARKER = _MARKER

# Module-level sink for state-migration events. Mirrors the sink in
# mage.state_store — setters in either module propagate to the same log
# so the audit trail of reads, writes, bootstraps, and migrations lives
# in one JSONL file.
_STATE_EVENTS_LOG: EventsLog | None = None


def set_events_log(events_log: EventsLog | None) -> None:
    """Set the module-level sink for state-migration events.

    Routes through :func:`mage.state_store.set_events_log` so both
    modules share one sink; callers can use either module's setter.
    """
    global _STATE_EVENTS_LOG
    _STATE_EVENTS_LOG = events_log
    _set_state_store_events_log(events_log)


def _emit(event_type: EventType, payload: dict[str, Any]) -> None:
    """Emit a state-migration event if a sink is configured; no-op otherwise."""
    if _STATE_EVENTS_LOG is None:
        return
    event = Event(
        timestamp=datetime.now(UTC),
        event_type=event_type,
        payload=payload,
    )
    _STATE_EVENTS_LOG.append_sync(event)


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

    Emits ``STATE_MIGRATED`` with ``{from_path, to_ref, backup_path,
    file_count}`` on success and ``STATE_MIGRATED_PARTIAL`` (with the
    raised error class and message) when any file fails to read or the
    rename collides; the partial event lets operators see in the audit
    trail which file blocked migration even though the exception aborts
    the call.
    """
    del command_runner  # Reserved for the restore implementation in Task 6.
    legacy = project_root / _LEGACY_DIR
    if not legacy.exists():
        return False
    if _is_migrated_marker_present(state_store):
        return False
    try:
        files = _walk_legacy_files(project_root)
        for path in files:
            rel = str(path.relative_to(legacy)).replace(os.sep, "/")
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise MageStateMigrationReadFailed(
                    f"failed to read {path}: {exc}"
                ) from exc
            state_store.write(rel, data)
        state_store.write(_MIGRATION_MARKER, b"")
    except MageStateMigrationError as exc:
        _emit(
            EventType.STATE_MIGRATED_PARTIAL,
            {
                "from_path": str(legacy),
                "to_ref": state_store.full_ref,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        raise
    ts = _now_timestamp(now)
    backup = _legacy_backup_path(project_root, ts)
    try:
        os.rename(legacy, backup)
    except FileExistsError as exc:
        partial = MageStateMigrationContention(
            f"backup path {backup} already exists; another migration ran in the same second"
        )
        _emit(
            EventType.STATE_MIGRATED_PARTIAL,
            {
                "from_path": str(legacy),
                "to_ref": state_store.full_ref,
                "error": f"{type(partial).__name__}: {partial}",
            },
        )
        raise partial from exc
    _emit(
        EventType.STATE_MIGRATED,
        {
            "from_path": str(legacy),
            "to_ref": state_store.full_ref,
            "backup_path": str(backup),
            "file_count": len(files),
        },
    )
    return True


def restore_from_backup(
    project_root: Path,
    state_store: StateStore,
    *,
    timestamp: str | None = None,
) -> str:
    """Inverse of maybe_migrate. Reads `.mage.bak.<ts>/` and writes into a
    fresh orphan-branch commit, then atomically swaps the ref.

    Snapshot-revert: the new commit contains ONLY the files from the
    backup — any files written to the orphan branch between migration
    and restore are dropped. ``_meta/.migrated`` is also absent (it is
    not part of the backup) so re-running ``maybe_migrate`` will
    re-rename `.mage.bak.<ts>/` back to `.mage/`.

    Returns the new ref SHA.
    """
    if timestamp is None:
        # Auto-discover the latest backup.
        backups = sorted(project_root.glob(f"{_BACKUP_PREFIX}*"))
        if not backups:
            raise MageStateMigrationError(f"no backup found under {project_root}")
        timestamp = backups[-1].name.removeprefix(_BACKUP_PREFIX)
    backup = _legacy_backup_path(project_root, timestamp)
    if not backup.exists():
        raise MageStateMigrationError(f"backup {backup} does not exist")

    # 1. Read backup files into an in-memory dict (path -> sha).
    blob_shas: dict[str, str] = {}
    for path in backup.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = str(path.relative_to(backup)).replace(os.sep, "/")
        data = path.read_bytes()
        result = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=project_root,
            input=data,
            capture_output=True,
            check=True,
        )
        blob_shas[rel] = result.stdout.decode("utf-8").strip()

    # 2. Build a fresh tree containing only the backup files.
    tree_sha = _mktree(project_root, blob_shas)

    # 3. Commit that tree as a fresh root commit on a sibling branch.
    commit_result = subprocess.run(
        [
            "git",
            "commit-tree",
            tree_sha,
            "-m",
            f"mage: restore from .mage.bak.{timestamp}",
        ],
        cwd=project_root,
        capture_output=True,
        check=True,
    )
    new_commit = commit_result.stdout.decode("utf-8").strip()

    # 3b. Record the sibling ref so the restoration is discoverable.
    sibling_ref = f"{state_store.full_ref}.restored.{timestamp}"
    subprocess.run(
        ["git", "update-ref", sibling_ref, new_commit],
        cwd=project_root,
        capture_output=True,
        check=True,
    )

    # 4. Atomically swap the live ref to the restored commit.
    #    Unconditional (no <oldvalue>): the sibling branch is freshly
    #    created so we have a stable pointer independent of the live
    #    ref's history.
    subprocess.run(
        ["git", "update-ref", state_store.full_ref, new_commit],
        cwd=project_root,
        capture_output=True,
        check=True,
    )
    _emit(
        EventType.STATE_MIGRATION_RESTORED,
        {
            "from_ts": timestamp,
            "to_ref": new_commit,
            "file_count": len(blob_shas),
        },
    )
    return new_commit


def _mktree(project_root: Path, entries: dict[str, str]) -> str:
    """Build a git tree object from a flat path->blob-sha mapping (recursive)."""
    if not entries:
        result = subprocess.run(
            ["git", "mktree"],
            cwd=project_root,
            capture_output=True,
            check=True,
        )
        return result.stdout.decode("utf-8").strip()
    files_at_root: dict[str, str] = {}
    subdirs: dict[str, dict[str, str]] = {}
    for path, sha in entries.items():
        if "/" in path:
            top, rest = path.split("/", 1)
            subdirs.setdefault(top, {})[rest] = sha
        else:
            files_at_root[path] = sha
    subdir_shas: dict[str, str] = {
        name: _mktree(project_root, entries) for name, entries in subdirs.items()
    }
    lines = [
        f"100644 blob {sha}\t{name}" for name, sha in sorted(files_at_root.items())
    ]
    lines += [f"040000 tree {sha}\t{name}" for name, sha in sorted(subdir_shas.items())]
    result = subprocess.run(
        ["git", "mktree"],
        cwd=project_root,
        input="\n".join(lines).encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()
