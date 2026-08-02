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
from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.orchestration.cosmetic_apply import apply_for_feature
from mage.orchestration.events import Event, EventsLog, EventType

logger = logging.getLogger(__name__)


class MappingArtifactWatcher:
    """Long-running daemon that auto-applies cosmetic queue items on MAPPING_SAVED.

    Tails `events.jsonl` via file-size polling. On each `MAPPING_SAVED`,
    diffs the new `feature_cosmetic_queue` against the last seen snapshot,
    then calls `apply_for_feature` per feature_id with new entries.

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
        """Request graceful shutdown."""
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
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.COSMETIC_WATCHER_STOPPED,
                    payload={"project_dir": str(self.project_dir)},
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
            rc = await apply_for_feature(self.project_dir, fid)
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
