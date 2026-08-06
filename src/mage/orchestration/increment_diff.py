"""Increment-relative diff capture.

Replaces the prior `git diff`-based capture in `RealizeStage.run_increment`,
which produced a repository-relative diff (cumulative prior-increment edits,
omitted staged changes, empty for new untracked files). This module
captures a pre-agent snapshot of the project tree and computes an
increment-relative unified diff after the agent runs.

Pure-Python. No subprocess. No events.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileSnapshot:
    """The pre-agent state of one path."""

    path: str  # project-relative, forward-slash separated
    exists: bool
    content: bytes | None  # None when not exists
    mode: int | None  # stat.S_IMODE; None when not exists
    truncated: bool = False  # True when content was clipped to MAX_BYTES
