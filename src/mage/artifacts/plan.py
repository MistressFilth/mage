"""PlanArtifact: digest-pinned Plan with finalize/load/revise operations.

The Plan's integrity is anchored to a SHA256 digest captured in the events log.
Any modification outside the mage plan revise flow raises PlanDigestMismatchError.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from mage.orchestration.events import Event, EventsLog, EventType


class PlanError(Exception):
    """Base exception for PlanArtifact errors."""


class PlanAlreadyFinalizedError(PlanError):
    """Raised when finalize() is called with a different digest than recorded."""


class PlanNotFinalizedError(PlanError):
    """Raised when load() is called but no prior FINALIZED/REVISED event exists."""


class PlanDigestMismatchError(PlanError):
    """Raised when load() finds the on-disk digest doesn't match the recorded digest."""


class PlanRevisionRequired(PlanError):
    """Raised by a stage when the Plan itself is wrong."""

    def __init__(
        self,
        reason: str,
        originating_stage: str,
        affected_behaviors: list[str],
    ) -> None:
        self.reason = reason
        self.originating_stage = originating_stage
        self.affected_behaviors = affected_behaviors
        super().__init__(reason)


def _recorded_digest(event: Event) -> str | None:
    return event.payload.get("plan_sha256") or event.payload.get("new_sha256")


class PlanArtifact:
    """Digest-pinned Plan operations."""

    @staticmethod
    def _compute_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _latest_event_for_path(
        events_log: EventsLog, plan_path: Path, event_types: tuple[EventType, ...]
    ) -> Event | None:
        plan_path_str = str(plan_path)
        candidates = [
            e for e in events_log.read_all()
            if e.event_type in event_types
            and e.payload.get("plan_path") == plan_path_str
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.timestamp)

    @classmethod
    async def finalize(
        cls, plan_path: Path, content: str, events_log: EventsLog
    ) -> str:
        """Write Plan atomically, compute SHA256, emit PLAN_FINALIZED.

        Returns plan_sha256. Idempotent if a prior PLAN_FINALIZED event has a
        matching digest (re-finalize allowed on match); raises
        PlanAlreadyFinalizedError on digest mismatch (caller must use revise).
        """
        digest = cls._compute_digest(content)

        existing = cls._latest_event_for_path(
            events_log, plan_path, (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        )
        if existing is not None:
            recorded = _recorded_digest(existing)
            if recorded != digest:
                raise PlanAlreadyFinalizedError(
                    f"Plan at {plan_path} already finalized with digest {recorded}; "
                    f"refusing to overwrite with different digest {digest}. "
                    f"Use revise() to record a revision."
                )

        # Atomic write
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(plan_path)

        await events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.PLAN_FINALIZED,
                payload={"plan_path": str(plan_path), "plan_sha256": digest},
            )
        )

        return digest

    @classmethod
    async def load(cls, plan_path: Path, events_log: EventsLog) -> str:
        """Read Plan with digest verification.

        Returns content on success. Raises PlanDigestMismatchError if on-disk
        digest != recorded digest in most recent event. Raises
        PlanNotFinalizedError if no prior FINALIZED/REVISED event exists.
        """
        # Find latest FINALIZED/REVISED event for this path
        event = cls._latest_event_for_path(
            events_log, plan_path, (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        )
        if event is None:
            raise PlanNotFinalizedError(
                f"No PLAN_FINALIZED or PLAN_REVISED event for {plan_path}; "
                f"refusing to read unverified Plan content."
            )

        recorded_digest = (
            _recorded_digest(event)
        )

        if not plan_path.exists():
            raise PlanNotFinalizedError(
                f"Plan file {plan_path} does not exist on disk."
            )

        content = plan_path.read_text(encoding="utf-8")
        computed_digest = cls._compute_digest(content)

        if computed_digest != recorded_digest:
            # Emit diagnostic event before raising
            await events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.PLAN_DIGEST_MISMATCH,
                    payload={
                        "plan_path": str(plan_path),
                        "recorded_sha256": recorded_digest,
                        "computed_sha256": computed_digest,
                        "recorded_event_type": event.event_type.value,
                        "recorded_event_at": event.timestamp.isoformat(),
                    },
                )
            )
            raise PlanDigestMismatchError(
                f"Plan at {plan_path} digest mismatch: "
                f"recorded={recorded_digest}, computed={computed_digest}"
            )

        return content

    @classmethod
    async def revise(
        cls,
        plan_path: Path,
        content: str,
        reason: str,
        human_approver: str,
        events_log: EventsLog,
    ) -> str:
        """Record a Plan revision after a halt.

        Writes Plan atomically, computes new SHA256, emits PLAN_REVISED event
        with {plan_path, old_sha256, new_sha256, reason, human_approver}.
        Returns new plan_sha256.
        """
        if not reason.strip():
            raise PlanError("revise() requires a non-empty reason")
        if not human_approver.strip():
            raise PlanError("revise() requires a non-empty human_approver")

        new_digest = cls._compute_digest(content)

        existing = cls._latest_event_for_path(
            events_log, plan_path, (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        )
        old_digest = (
            _recorded_digest(existing)
            if existing is not None
            else None
        )

        # Atomic write
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(plan_path)

        await events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.PLAN_REVISED,
                payload={
                    "plan_path": str(plan_path),
                    "old_sha256": old_digest,
                    "new_sha256": new_digest,
                    "reason": reason,
                    "human_approver": human_approver,
                },
            )
        )

        return new_digest
