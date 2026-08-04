"""PID file lifecycle for the `mage cosmetic watch` daemon.

Path: `<project_dir>/.mage/cosmetic_watcher.pid`. Atomic write (temp +
rename + fsync). Best-effort removal on stop. The daemon does not
block on file write or read; the file is coordination, not state.

File format (single line): ``<pid>:<start_time>\n``. ``start_time`` is
the value of the 22nd field in ``/proc/<pid>/stat`` (the kernel's
clock-tick count at process start). It is captured at write time and
verified at liveness time so the daemon cannot SIGKILL a different
process that has reused the same integer PID.
"""

from __future__ import annotations

import os
from pathlib import Path

_PID_DIR = Path(".mage")
_PID_FILE = "cosmetic_watcher.pid"


def pid_file_path(project_dir: Path) -> Path:
    """Absolute path to the cosmetic watcher PID file under `project_dir`."""
    return project_dir / _PID_DIR / _PID_FILE


def _proc_start_time(pid: int) -> int | None:
    """Return field 22 (starttime) of ``/proc/<pid>/stat`` as an int.

    Returns None when the field cannot be read. Linux only.
    """
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None
    # The `comm` field can contain spaces and parens; the safe parse
    # anchor is the LAST `)` of the comm field. Everything after that
    # is whitespace-separated fields, starting with `state`.
    close = text.rfind(")")
    if close < 0 or close + 1 >= len(text):
        return None
    tail = text[close + 1 :].split()
    # After `)`: state(1), ppid(2), pgrp(3), session(4), tty_nr(5),
    # tpgid(6), flags(7), minflt(8), cminflt(9), majflt(10), cmajflt(11),
    # utime(12), stime(13), cutime(14), cstime(15), priority(16),
    # nice(17), num_threads(18), itrealvalue(19), starttime(20).
    if len(tail) < 20:
        return None
    try:
        return int(tail[19])
    except ValueError:
        return None


def write_pid(project_dir: Path, pid: int) -> Path:
    """Atomically write `pid` and its start_time to the PID file.

    Format: ``<pid>:<start_time>\\n``. When start_time cannot be
    determined (non-Linux, no /proc), writes ``<pid>:\\n`` with an
    empty start_time. The empty start_time is treated as "no
    identity" by ``is_alive_with_start`` and the PID file is rejected
    as stale at liveness time — so the worst case is a missed
    cleanup, never a wrong-process SIGKILL.

    Returns the file path.
    """
    path = pid_file_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    start_time = _proc_start_time(pid)
    payload = f"{pid}:{start_time if start_time is not None else ''}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(path)
    return path


def remove_pid(project_dir: Path) -> bool:
    """Best-effort removal. Returns True if a file was removed."""
    path = pid_file_path(project_dir)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def read_pid(project_dir: Path) -> tuple[int, int | None] | None:
    """Parse the PID file. Returns ``(pid, start_time)`` or None.

    ``start_time`` is None when the file has no start_time field (the
    legacy format, or the new format written on a host where
    ``/proc/<pid>/stat`` was unreadable). Callers that need identity
    verification must use ``is_alive_with_start`` and treat a None
    start_time as "stale".
    """
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


def is_alive(pid: int) -> bool:
    """Liveness probe via `kill(pid, 0)`. Returns False for pid <= 0.

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


def is_alive_with_start(pid: int, start_time: int | None) -> bool:
    """Verify a PID is alive AND matches the recorded start_time.

    Returns False when:
    - ``pid <= 0``
    - the process is not alive
    - ``start_time`` is None (no identity recorded; treat as stale)
    - the live process's current start_time differs from ``start_time``
      (PID was reused by a different process)

    This is the only liveness check that should precede a `kill(2)` or
    `os.kill(SIGKILL)` to a PID read from disk.
    """
    if pid <= 0 or start_time is None:
        return False
    if not is_alive(pid):
        return False
    current = _proc_start_time(pid)
    return current is not None and current == start_time


def _pid_exists_other(pid: int) -> bool:
    """Fallback liveness check via `/proc/<pid>` on POSIX only."""
    try:
        return Path(f"/proc/{pid}").exists()
    except OSError:
        return False
