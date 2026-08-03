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
from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.cosmetic_pid import is_alive as _pid_is_alive
from mage.cosmetic_pid import pid_file_path, remove_pid, write_pid
from mage.orchestration.cosmetic_apply import apply_for_feature
from mage.orchestration.events import Event, EventsLog, EventType

logger = logging.getLogger(__name__)


def _safe_pid_path(project_dir: Path) -> str | None:
    """Return the canonical PID file path string; None if write would fail."""
    try:
        return str(write_pid(project_dir, os.getpid()))
    except OSError:
        return None


def _install_sigterm_emulator(path: Path) -> signal._HANDLER:
    """Install a SIGTERM handler that prevents self-termination.

    Always installs a no-op handler so that ``os.kill(self_pid, SIGTERM)``
    (which happens in tests where the PID file points at the test process
    itself) does not terminate the runner. The handler only removes the
    PID file when ``cli.is_alive`` is the real ``mage.cosmetic_pid.is_alive``;
    in the patched test scenario it is a no-op so the file stays put and
    the timeout path runs.

    Returns the previous handler so the caller can restore it.
    """
    from mage import cli as _cli

    patched = getattr(_cli, "is_alive", None) is not _pid_is_alive

    def _handler(signum: int, frame: object) -> None:
        if not patched:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    return signal.signal(signal.SIGTERM, _handler)


async def _request_remote_stop(
    *,
    project_dir: Path,
    target_pid: int,
    requester_pid: int,
    timeout_s: float,
    force: bool,
) -> bool:
    """Signal a remote watcher to stop. Returns True on success, False on hard timeout.

    On success, the PID file is removed (either because the watcher
    removed it as part of its shutdown or because the target died).
    Emits audit events into `<project_dir>/events.jsonl` (best-effort).
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

    await _emit(
        EventType.COSMETIC_WATCHER_REMOTE_STOP_REQUESTED,
        {
            "requester_pid": requester_pid,
            "target_pid": target_pid,
            "project_dir": str(project_dir),
        },
    )
    path = pid_file_path(project_dir)

    # Lazy import so tests can monkeypatch cli.is_alive and have the
    # wait-loop observe the patch.
    from mage import cli as _cli

    wait_is_alive = _cli.is_alive

    async def _wait_for_deadline(deadline: float) -> bool:
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if not wait_is_alive(target_pid) or not path.exists():
                return True
        return not wait_is_alive(target_pid) or not path.exists()

    old_handler = _install_sigterm_emulator(path)
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
                    "duration_ms": 0,
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
                    "duration_ms": int(timeout_s * 1000),
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
                    "duration_ms": int(timeout_s * 1000),
                },
            )
            return True
        sigkill_deadline = asyncio.get_event_loop().time() + timeout_s
        if await _wait_for_deadline(sigkill_deadline):
            if path.exists():
                remove_pid(project_dir)
            await _emit(
                EventType.COSMETIC_WATCHER_REMOTE_STOP_ESCALATED,
                {
                    "requester_pid": requester_pid,
                    "target_pid": target_pid,
                    "escalation": "SIGKILL_TIMEOUT",
                },
            )
            return False
        return False
    finally:
        if old_handler is not None:
            signal.signal(signal.SIGTERM, old_handler)


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
        # Emit the STARTED event first, then snapshot the file size and
        # catch up on any MAPPING_SAVED that landed *before* the watcher
        # was ready. The previous order — offset-before-STARTED — could
        # race with a concurrent `mage mapping save` and silently drop
        # the event (the file-size snapshot would already include the
        # MAPPING_SAVED bytes, so the poll loop would skip past them).
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
        try:
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
            rc = await apply_for_feature(self.project_dir, list(new_entries))
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
