"""PID file lifecycle for the `mage cosmetic watch` daemon.

Path: `<project_dir>/.mage/cosmetic_watcher.pid`. Atomic write (temp +
rename + fsync). Best-effort removal on stop. The daemon does not
block on file write or read; the file is coordination, not state.
"""

from __future__ import annotations

import os
from pathlib import Path

_PID_DIR = Path(".mage")
_PID_FILE = "cosmetic_watcher.pid"


def pid_file_path(project_dir: Path) -> Path:
    """Absolute path to the cosmetic watcher PID file under `project_dir`."""
    return project_dir / _PID_DIR / _PID_FILE


def write_pid(project_dir: Path, pid: int) -> Path:
    """Atomically write `pid` to the PID file. Returns the file path.

    Creates `<project_dir>/.mage/` if missing. Uses temp + fsync +
    rename for atomicity across POSIX filesystems.
    """
    path = pid_file_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{pid}\n")
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


def read_pid(project_dir: Path) -> int | None:
    """Parse the PID file. Returns None on missing or non-integer content."""
    path = pid_file_path(project_dir)
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except ValueError:
        return None


def is_alive(pid: int) -> bool:
    """Liveness probe via `kill(pid, 0)`. Returns False for pid <= 0."""
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


def _pid_exists_other(pid: int) -> bool:
    """Fallback liveness check via `/proc/<pid>` on POSIX only."""
    try:
        return Path(f"/proc/{pid}").exists()
    except OSError:
        return False
