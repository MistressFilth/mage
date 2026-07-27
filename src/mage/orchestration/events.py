"""Append-only events log for the orchestration state machine."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class EventType(str, Enum):
    """Types of orchestration events."""

    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    SCENARIO_STATE_CHANGED = "scenario_state_changed"
    FINDING_RECORDED = "finding_recorded"
    BID_ASSIGNED = "bid_assigned"
    REVERSION_LOGGED = "reversion_logged"
    COSMETIC_REVIEW_QUEUED = "cosmetic_review_queued"
    HUMAN_REVIEW_REQUESTED = "human_review_requested"

    # Plan 2 — Decomposition stage
    DECOMPOSITION_STARTED = "decomposition_started"
    DECOMPOSITION_COMPLETED = "decomposition_completed"

    # Plan 2 — behavior enumeration sub-step
    BEHAVIORS_ENUMERATED = "behaviors_enumerated"

    # Plan 2 — Plan lifecycle
    PLAN_FINALIZED = "plan_finalized"
    PLAN_REVISED = "plan_revised"
    PLAN_DIGEST_MISMATCH = "plan_digest_mismatch"

    # Plan 2 — halt/recovery
    HALT_PERSISTED = "halt_persisted"

    # Plan 5 placeholder (defined here so events log schema is stable)
    BEHAVIORS_REVISED = "behaviors_revised"


class Event(BaseModel):
    """One event in the log."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    event_type: EventType
    payload: dict


class EventsLog:
    """Append-only JSONL log of orchestration events."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure the file exists for empty-log reads.
        if not self.log_path.exists():
            self.log_path.touch()

    def append(self, event: Event) -> None:
        """Append a single event to the log (JSONL format, one event per line)."""
        line = event.model_dump_json()
        with self.log_path.open("a") as f:
            f.write(line + "\n")

    def read_all(self) -> list[Event]:
        """Read all events from the log in order."""
        return [Event.model_validate_json(line) for line in self._read_lines()]

    def read_since(self, timestamp: datetime) -> list[Event]:
        """Read events with timestamp strictly after the given cutoff."""
        events = self.read_all()
        return [e for e in events if e.timestamp > timestamp]

    def _read_lines(self) -> list[str]:
        """Return non-empty lines from the log file."""
        with self.log_path.open() as f:
            return [line for line in f.read().splitlines() if line.strip()]
