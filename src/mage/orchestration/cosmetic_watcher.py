"""Long-running watcher that auto-applies cosmetic queue items on MAPPING_SAVED.

Plan 11: tails `events.jsonl`, diffs the mapping's
`feature_cosmetic_queue` against the last seen snapshot, and calls
`apply_for_feature` per feature_id with new entries. Idempotency from
Plan 10 (`CosmeticAppliedState`) protects against double-application.

Note: the on-disk YAML/JSON key remains `feature_cosmetic_queue` via a
Pydantic `Field(alias=...)` on `MappingArtifact`; the in-memory attribute
accessed below is `mapping.cosmetic_findings`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.cosmetic_pid import is_alive_with_start, pid_file_path, remove_pid, write_pid
from mage.orchestration.cosmetic_apply import apply_for_feature
from mage.orchestration.events import Event, EventsLog, EventType

logger = logging.getLogger(__name__)


def _safe_pid_path(project_dir: Path) -> str | None:
    """Return the canonical PID file path string; None if write would fail."""
    try:
        return str(write_pid(project_dir, os.getpid()))
    except OSError:
        return None


async def _request_remote_stop(
    *,
    project_dir: Path,
    target_pid: int,
    target_start_time: int | None,
    requester_pid: int,
    timeout_s: float,
    force: bool,
) -> bool:
    """Signal a remote watcher to stop. Returns True on success, False on hard timeout.

    Liveness is verified via ``is_alive_with_start`` so a SIGKILL can
    never land on a different process that has reused the recorded PID.
    On success, the PID file is removed (either because the watcher
    removed it as part of its shutdown or because the target died).
    Emits audit events into `<project_dir>/events.jsonl` (best-effort).

    Every audit event in this routine uses a single monotonic clock
    (``start`` at function entry) so the elapsed_ms in the audit log
    reflects actual wall time at the moment the terminal decision was
    made. The SIGKILL branch starts a fresh monotonic when SIGKILL
    is dispatched so the SIGKILL_TIMEOUT escalation reports the
    SIGKILL-window elapsed, not the cumulative SIGTERM+SIGKILL time.
    """
    log_path = project_dir / "events.jsonl"
    log: EventsLog | None = None
    if log_path.parent.exists():
        log = EventsLog(log_path)

    async def _emit(event_type: EventType, payload: dict) -> None:
        if log is None:
            return
        await log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=event_type,
                payload=payload,
            )
        )

    start = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    await _emit(
        EventType.COSMETIC_WATCHER_REMOTE_STOP_REQUESTED,
        {
            "requester_pid": requester_pid,
            "target_pid": target_pid,
            "project_dir": str(project_dir),
        },
    )
    path = pid_file_path(project_dir)

    async def _wait_for_deadline(deadline: float) -> bool:
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if (
                not is_alive_with_start(target_pid, target_start_time)
                or not path.exists()
            ):
                return True
        return (
            not is_alive_with_start(target_pid, target_start_time) or not path.exists()
        )

    try:
        sigterm_deadline = asyncio.get_event_loop().time() + timeout_s
        try:
            os.kill(target_pid, signal.SIGTERM)
        except ProcessLookupError:
            if path.exists():
                remove_pid(project_dir)
            await _emit(
                EventType.COSMETIC_WATCHER_REMOTE_STOP_SUCCEEDED,
                {
                    "requester_pid": requester_pid,
                    "target_pid": target_pid,
                    "duration_ms": _elapsed_ms(),
                },
            )
            return True
        if await _wait_for_deadline(sigterm_deadline):
            if path.exists():
                remove_pid(project_dir)
            await _emit(
                EventType.COSMETIC_WATCHER_REMOTE_STOP_SUCCEEDED,
                {
                    "requester_pid": requester_pid,
                    "target_pid": target_pid,
                    "duration_ms": _elapsed_ms(),
                },
            )
            return True
        if not force:
            await _emit(
                EventType.COSMETIC_WATCHER_REMOTE_STOP_ESCALATED,
                {
                    "requester_pid": requester_pid,
                    "target_pid": target_pid,
                    "escalation": "SIGTERM_TIMEOUT",
                    "duration_ms": _elapsed_ms(),
                },
            )
            return False
        try:
            os.kill(target_pid, signal.SIGKILL)
        except ProcessLookupError:
            if path.exists():
                remove_pid(project_dir)
            await _emit(
                EventType.COSMETIC_WATCHER_REMOTE_STOP_SUCCEEDED,
                {
                    "requester_pid": requester_pid,
                    "target_pid": target_pid,
                    "duration_ms": _elapsed_ms(),
                },
            )
            return True
        # Fresh monotonic for the SIGKILL window so SIGKILL_TIMEOUT
        # reports the time spent waiting on SIGKILL alone, not the
        # SIGTERM+SIGKILL cumulative elapsed.
        sigkill_start = time.monotonic()
        sigkill_deadline = asyncio.get_event_loop().time() + timeout_s
        if await _wait_for_deadline(sigkill_deadline):
            if path.exists():
                remove_pid(project_dir)
            await _emit(
                EventType.COSMETIC_WATCHER_REMOTE_STOP_SUCCEEDED,
                {
                    "requester_pid": requester_pid,
                    "target_pid": target_pid,
                    "duration_ms": int((time.monotonic() - sigkill_start) * 1000),
                },
            )
            return True
        await _emit(
            EventType.COSMETIC_WATCHER_REMOTE_STOP_ESCALATED,
            {
                "requester_pid": requester_pid,
                "target_pid": target_pid,
                "escalation": "SIGKILL_TIMEOUT",
                "duration_ms": int((time.monotonic() - sigkill_start) * 1000),
            },
        )
        return False
    finally:
        # No SIGTERM handler installed in production; the SIGTERM
        # signal flows to whatever is bound (typically the test runner
        # or the orchestrator). See the test suite for the test-side
        # helper that intercepts SIGTERM in this process.
        pass


def _events_log_for(project_dir: Path) -> EventsLog:
    """Return an EventsLog for `<project_dir>/events.jsonl`."""
    return EventsLog(project_dir / "events.jsonl")


class MappingArtifactWatcher:
    """Long-running daemon that auto-applies cosmetic queue items on MAPPING_SAVED.

    Tails `events.jsonl` via file-size polling. On each `MAPPING_SAVED`,
    diffs the new `feature_cosmetic_queue` against the last seen snapshot,
    then calls `apply_for_feature` per feature_id with the new sub_bids.

    `stop()` is the only way to terminate `run()` cleanly. The daemon
    emits `COSMETIC_WATCHER_STARTED` on entry and `COSMETIC_WATCHER_STOPPED`
    on exit.

    The on-disk key (`feature_cosmetic_queue`) and the in-memory attribute
    (`mapping.cosmetic_findings`) are aliased via
    ``Field(alias="feature_cosmetic_queue")`` on ``MappingArtifact``; the
    code below reads the latter.
    """

    def __init__(
        self,
        project_dir: Path,
        *,
        poll_interval_ms: int = 250,
        events_log: EventsLog | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.poll_interval_ms = poll_interval_ms
        self.events_log = events_log or EventsLog(self.project_dir / "events.jsonl")
        self._stop = False
        self._last_seen: dict[str, frozenset[str]] = {}

    def stop(self) -> None:
        """Request graceful shutdown. Removes PID file (best-effort)."""
        self._stop = True

    async def run(self) -> None:
        """Long-running loop. Returns on `stop()`."""
        log_path = self.events_log.log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Plan 28b: the try/finally now wraps the STARTED append, the
        # catch-up _handle_mapping_saved(), and the poll loop. Before P28b
        # the catch-up ran outside the try:, so a ValidationError or
        # refiner network error left the audit trail dangling on
        # COSMETIC_WATCHER_STARTED and the PID file on disk. The previous
        # order — STARTED-before-catch-up — is preserved; the try: scope
        # is widened to cover both the STARTED append and the catch-up.
        try:
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.COSMETIC_WATCHER_STARTED,
                    payload={
                        "project_dir": str(self.project_dir),
                        "poll_interval_ms": self.poll_interval_ms,
                        "pid": os.getpid(),
                        "pid_file_path": _safe_pid_path(self.project_dir),
                    },
                )
            )
            await self._handle_mapping_saved()
            offset = log_path.stat().st_size if log_path.exists() else 0
            while not self._stop:
                await asyncio.sleep(self.poll_interval_ms / 1000)
                current_size = log_path.stat().st_size if log_path.exists() else 0
                if current_size < offset:
                    offset = 0  # rotated/truncated; reset
                if current_size <= offset:
                    continue
                with log_path.open("rb") as f:
                    f.seek(offset)
                    new_bytes = f.read(current_size - offset)
                offset = current_size
                for line in new_bytes.splitlines():
                    if not line:
                        continue
                    try:
                        event = Event.model_validate_json(line)
                    except (OSError, ValueError) as e:
                        logger.debug(
                            "continuing after %s in cosmetic watcher: %s",
                            type(e).__name__,
                            e,
                        )
                        continue
                    if event.event_type != EventType.MAPPING_SAVED:
                        continue
                    await self._handle_mapping_saved()
        finally:
            removed = remove_pid(self.project_dir)
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.COSMETIC_WATCHER_STOPPED,
                    payload={
                        "project_dir": str(self.project_dir),
                        "pid_file_removed": removed,
                    },
                )
            )

    async def _handle_mapping_saved(self) -> None:
        """Re-load mapping, diff, apply per-feature."""
        from mage.artifacts.mapping import MappingArtifact

        try:
            mapping = MappingArtifact.load(self.project_dir / "mapping.yaml")
        except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.COSMETIC_WATCHER_FAILED,
                    payload={
                        "reason": "load-failed",
                        "error_type": type(exc).__name__,
                    },
                )
            )
            return
        new_seen: dict[str, frozenset[str]] = {}
        for entry in mapping.cosmetic_findings:
            fid = entry.get("feature_id")
            sb = entry.get("sub_bid")
            if not isinstance(fid, str) or not isinstance(sb, str):
                continue
            new_seen[fid] = new_seen.get(fid, frozenset()) | {sb}
        for fid, sub_bids in new_seen.items():
            new_entries = sub_bids - self._last_seen.get(fid, frozenset())
            if not new_entries:
                continue
            # Pass feature_id so apply_for_feature narrows the queue
            # by the loop's current feature_id. Without this narrowing,
            # a sub_bid that exists in another feature would also be
            # picked up here.
            rc = await apply_for_feature(
                self.project_dir, list(new_entries), feature_id=fid
            )
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.COSMETIC_WATCHER_APPLIED_FEATURE,
                    payload={
                        "feature_id": fid,
                        "sub_bids_count": len(new_entries),
                        "rc": rc,
                    },
                )
            )
        self._last_seen = new_seen
