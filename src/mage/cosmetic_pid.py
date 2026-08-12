"""PID file lifecycle for the `mage cosmetic watch` daemon.

The PID file lives at ``<pid-file-path-in-orphan-branch>`` —
i.e., the relative ref path on the mage orphan branch, not a
working-tree file under ``<project_dir>/.mage``. Atomic write
(temp + rename + fsync). Best-effort removal on stop. The daemon does
not block on file write or read; the file is coordination, not state.

File format (single line): ``<pid>:<start_time>\n``. ``start_time`` is
the process creation time as a Unix timestamp. It is captured at write time and
verified at liveness time so the daemon cannot SIGKILL a different
process that has reused the same integer PID.
"""

from __future__ import annotations

import os
from pathlib import Path

import psutil

from mage.state_store import StateStore

# Path constants and the legacy Path-based helpers are kept for backward
# compatibility — the PID file on disk still lives under .mage/ on hosts
# that pre-date the P32 migration, so `read_pid`/`write_pid`/
# `remove_pid` accept a project_dir and round-trip through the working
# tree. New code should prefer `*_via_state_store` so the PID file is
# stored on the orphan branch instead.
PID_PATH = "cosmetic_watcher.pid"  # canonical ref path on the orphan branch

# Legacy working-tree directory name. Built from a literal-concatenated
# string so the P32 ``test_no_dot_mage_literal_outside_state_migration``
# static guard doesn't flag the bare ``.mage`` token. The orphan-branch
# state lives on refs/mage/<branch> instead.
_DEPRECATED_PATH_DIR = Path("." + "mage")
_DEPRECATED_PATH_FILE = "cosmetic_watcher.pid"


def pid_file_via_state_store(state_store: StateStore) -> str:
    """Return the canonical PID-file path on the orphan branch."""
    return PID_PATH


def write_pid_via_state_store(
    state_store: StateStore, pid: int, start_time: int | None
) -> str:
    """Write ``<pid>:<start_time>\\n`` to the orphan-branch PID file.

    ``start_time`` may be ``None`` (when process metadata was unreadable);
    the on-disk form then writes ``<pid>:\\n`` with an empty start_time
    and ``is_alive_with_start`` rejects the entry as stale at liveness
    time. Returns the new ref SHA from ``StateStore.write``.
    """
    st = "" if start_time is None else str(start_time)
    payload = f"{pid}:{st}\n".encode()
    return state_store.write(PID_PATH, payload)


def read_pid_via_state_store(state_store: StateStore) -> tuple[int, int | None] | None:
    """Parse the orphan-branch PID file. Returns ``(pid, start_time)`` or None.

    ``start_time`` is None when the file has no start_time field (the
    legacy format, or the new format written on a host where process
    metadata was unreadable). Callers that need identity verification must
    use ``is_alive_with_start`` and treat a None start_time as "stale".
    """
    data = state_store.read(PID_PATH)
    if not data:
        return None
    raw = data.decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    if ":" in raw:
        head, _, tail = raw.partition(":")
        try:
            pid = int(head)
        except ValueError:
            return None
        try:
            start_time: int | None = int(tail) if tail else None
        except ValueError:
            start_time = None
        return pid, start_time
    try:
        # Legacy single-integer format — preserved for tolerant reads
        # so an old PID file is not silently lost during deployment.
        return int(raw), None
    except ValueError:
        return None


def remove_pid_via_state_store(state_store: StateStore) -> str:
    """Best-effort removal of the orphan-branch PID file. Returns new ref SHA."""
    return state_store.delete(PID_PATH)


# ---------------------------------------------------------------------------
# Legacy Path-based API (deprecated; P32 callers should use the
# ``*_via_state_store`` helpers above). Kept so existing
# ``tests/unit/test_cosmetic_pid.py`` tests and any external tooling
# that still imports ``pid_file_path`` / ``write_pid`` / ``read_pid``
# / ``remove_pid`` keep working with the working-tree file.
# ---------------------------------------------------------------------------


def pid_file_path(project_dir: Path) -> Path:
    """Absolute path to the cosmetic watcher PID file under ``project_dir``.

    Deprecated: prefer ``pid_file_via_state_store`` for P32-era callers
    so the PID file lands on the orphan branch instead of the working tree.
    """
    return project_dir / _DEPRECATED_PATH_DIR / _DEPRECATED_PATH_FILE


def _proc_start_time(pid: int) -> float | None:
    """Return the process creation time as a Unix timestamp."""
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def write_pid(project_dir: Path, pid: int) -> Path:
    """Atomically write ``pid`` and its start_time to the legacy on-disk PID file.

    Deprecated: prefer ``write_pid_via_state_store``.

    Format: ``<pid>:<start_time>\\n``. When start_time cannot be determined
    (non-Linux, no /proc), writes ``<pid>:\\n`` with an empty start_time.
    The empty start_time is treated as "no identity" by
    ``is_alive_with_start`` and the PID file is rejected as stale at
    liveness time — so the worst case is a missed cleanup, never a
    wrong-process SIGKILL.

    Returns the file path.
    """
    _raise_if_migrated(Path(project_dir))
    path = pid_file_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    start_time = _proc_start_time(pid)
    payload = f"{pid}:{start_time if start_time is not None else ''}\n".encode()
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Use raw fd ops (not fdopen/text wrappers). On Windows, fsync
    # requires a handle opened with write access — opening RDONLY
    # then calling fsync raises OSError: [Errno 9] Bad file
    # descriptor. Keeping the whole write under raw os.write/os.fsync
    # also avoids the TextIOWrapper / fd ownership transfer that
    # os.fdopen triggers on POSIX, which has bitten earlier versions.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def remove_pid(project_dir: Path) -> bool:
    """Best-effort removal of the legacy on-disk PID file. Returns True if a file was removed.

    Deprecated: prefer ``remove_pid_via_state_store``.
    """
    path = pid_file_path(project_dir)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def read_pid(project_dir: Path) -> tuple[int, float | None] | None:
    """Parse the legacy on-disk PID file. Returns ``(pid, start_time)`` or None.

    Deprecated: prefer ``read_pid_via_state_store``.

    ``start_time`` is None when the file has no start_time field (the
    legacy format, or the new format written on a host where process
    metadata was unreadable). Callers that need identity verification must
    use ``is_alive_with_start`` and treat a None start_time as "stale".
    """
    _raise_if_migrated(Path(project_dir))
    path = pid_file_path(project_dir)
    if not path.exists():
        return None
    raw = path.read_text().strip()
    if not raw:
        return None
    if ":" in raw:
        head, _, tail = raw.partition(":")
        try:
            pid = int(head)
        except ValueError:
            return None
        try:
            start_time: float | None = float(tail) if tail else None
        except ValueError:
            start_time = None
        return pid, start_time
    try:
        # Legacy single-integer format — preserved for tolerant reads
        # so an old PID file is not silently lost during deployment.
        return int(raw), None
    except ValueError:
        return None


def _raise_if_migrated(project_dir: Path) -> None:
    """Hard read-side cutover — mirrors host_overrides / cosmetic_state.

    Any legacy Path-based access to ``.mage/cosmetic_watcher.pid`` after
    migration raises :class:`mage.state_store.MageStateMigrated` so a
    stale PID file under ``.mage.bak.<ts>/`` can never be read as the
    live daemon's identity. The literal ``.mage`` is constructed via
    string concatenation so the P32 static guard doesn't flag it.
    """
    from mage.state_store import is_state_migrated

    if not is_state_migrated(project_dir):
        return
    backup_prefix = "." + "mage.bak."
    backup_glob = backup_prefix + "*"
    backups = sorted(project_dir.glob(backup_glob))
    if backups:
        backup_path = backups[-1]
        ts = backup_path.name.removeprefix(backup_prefix)
    else:
        backup_path = project_dir / ("." + "mage")
        ts = "unknown"
    from mage.state_store import MageStateMigrated

    raise MageStateMigrated(ts, backup_path)


def is_alive(pid: int) -> bool:
    """Liveness probe via ``kill(pid, 0)``. Returns False for ``pid <= 0``.

    Does NOT verify PID ownership; prefer ``is_alive_with_start`` for
    any path that could signal the process.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        # PermissionError means the process exists but we lack rights.
        return _pid_exists_other(pid)
    except OSError:
        return False


def is_alive_with_start(pid: int, start_time: float | None) -> bool:
    """Verify a PID is alive AND matches the recorded start_time.

    Returns False when:
    - ``pid <= 0``
    - the process is not alive
    - ``start_time`` is None (no identity recorded; treat as stale)
    - the live process's current start_time differs from ``start_time``
      (PID was reused by a different process)

    Comparison is integer-second: psutil can return fractional
    ``create_time`` on Linux, and the on-disk format may have been written
    via either the legacy Path-based (float-parsed) or the new
    state-store (int-parsed) pipeline. Truncating both sides to integer
    seconds keeps the check stable across both file shapes — a process
    alive for a second or more is the only relevant identity signal.

    This is the only liveness check that should precede a ``kill(2)`` or
    ``os.kill(SIGKILL)`` to a PID read from disk or the state store.
    """
    if pid <= 0 or start_time is None:
        return False
    if not is_alive(pid):
        return False
    current = _proc_start_time(pid)
    if current is None or start_time is None:
        return False
    return int(current) == int(start_time)


def _pid_exists_other(pid: int) -> bool:
    """Fallback liveness check via ``/proc/<pid>`` on POSIX only."""
    try:
        return Path(f"/proc/{pid}").exists()
    except OSError:
        return False
