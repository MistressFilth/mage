"""Append-only events log for the orchestration state machine."""

from __future__ import annotations

import asyncio
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

    # Plan 3 — Inscribe stage
    INSCRIBE_STARTED = "inscribe_started"
    INSCRIBE_COMPLETED = "inscribe_completed"
    BEHAVIOR_INSCRIBE_STARTED = "behavior_inscribe_started"
    BEHAVIOR_INSCRIBE_COMPLETED = "behavior_inscribe_completed"
    SCENARIO_DRAFTED = "scenario_drafted"
    MECHANICAL_PRECHECK_PASSED = "mechanical_precheck_passed"
    MECHANICAL_PRECHECK_FAILED = "mechanical_precheck_failed"
    REVIEWER_VERDICT_RECORDED = "reviewer_verdict_recorded"
    REVIEW_AGGREGATE_RECORDED = "review_aggregate_recorded"
    SCENARIO_APPROVED = "scenario_approved"
    SCENARIO_NEEDS_REFACTOR = "scenario_needs_refactor"
    REVIEW_HALT_PERSISTED = "review_halt_persisted"

    # Plan 4 — Etch stage
    ETCH_STARTED = "etch_started"
    ETCH_RED_CONFIRMED = "etch_red_confirmed"
    ETCH_COMPLETED = "etch_completed"

    # Plan 4 — Realize stage
    REALIZE_STARTED = "realize_started"
    REALIZE_INCREMENT_DONE = "realize_increment_done"
    REALIZE_COMPLETED = "realize_completed"
    SCENARIO_OUTER_GREEN = "scenario_outer_green"
    SCENARIO_LIVE = "scenario_live"

    # Plan 4 — Inspect-loop stage
    INSPECT_LOOP_STARTED = "inspect_loop_started"
    INSPECT_LOOP_PASSED = "inspect_loop_passed"
    INSPECT_LOOP_FAILED = "inspect_loop_failed"
    INSPECT_LOOP_COMPLETED = "inspect_loop_completed"

    # Plan 12 — InspectLoop feature_id threading
    INSPECT_LOOP_FEATURE_RESOLVED = "inspect_loop_feature_resolved"

    INSPECT_JOURNAL_APPENDED = "inspect_journal_appended"
    SCENARIO_HALT_PERSISTED = "scenario_halt_persisted"

    # Plan 5 placeholder members (kept here so events log schema is stable)
    INSPECT_FEATURE_STARTED = "inspect_feature_started"
    INSPECT_FEATURE_FINALIZED = "inspect_feature_finalized"

    # Plan 5 — InspectFeature stage (full set)
    INSPECT_FEATURE_PASSED = "inspect_feature_passed"
    INSPECT_FEATURE_HALT_PERSISTED = "inspect_feature_halt_persisted"
    INSPECT_FEATURE_COMPLETED = "inspect_feature_completed"
    FIX_WAVE_DISPATCHED = "fix_wave_dispatched"

    # Plan 5 — SettleFeature stage
    SETTLE_FEATURE_STARTED = "settle_feature_started"
    SETTLE_COSMETIC_QUEUED = "settle_cosmetic_queued"
    SETTLE_TESTS_FAILED = "settle_tests_failed"
    SETTLE_FEATURE_FINALIZED = "settle_feature_finalized"
    SETTLE_FEATURE_COMPLETED = "settle_feature_completed"
    SETTLE_BRANCH_DISCARDED = "settle_branch_discarded"
    SETTLE_MERGE_ROLLED_BACK = "settle_merge_rolled_back"
    SETTLE_CLEANUP_SKIPPED = "settle_cleanup_skipped"

    # Plan 7 — Discipline enforcement
    SCENARIO_REVERTED_TO_INSCRIBING = "scenario_reverted_to_inscribing"
    SCENARIO_REVISION_REQUESTED = "scenario_revision_requested"
    SCENARIO_SUPERSESSION_REQUESTED = "scenario_supersession_requested"
    SCENARIO_DEPRECATED = "scenario_deprecated"

    # Plan 9 — Cosmetic apply pipeline
    COSMETIC_ITEM_APPLIED = "cosmetic_item_applied"
    COSMETIC_ITEM_SKIPPED = "cosmetic_item_skipped"
    COSMETIC_APPLY_FAILED = "cosmetic_apply_failed"
    COSMETIC_REFINER_FALLBACK = "cosmetic_refiner_fallback"

    # Plan 11 — Mapping save signal + cosmetic watcher lifecycle
    MAPPING_SAVED = "mapping_saved"
    COSMETIC_WATCHER_STARTED = "cosmetic_watcher_started"
    COSMETIC_WATCHER_STOPPED = "cosmetic_watcher_stopped"
    COSMETIC_WATCHER_APPLIED_FEATURE = "cosmetic_watcher_applied_feature"
    COSMETIC_WATCHER_FAILED = "cosmetic_watcher_failed"


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
        self._lock: asyncio.Lock | None = (
            None  # lazy; asyncio.Lock requires a running loop
        )

    def _get_lock(self) -> asyncio.Lock:
        """Return the per-instance asyncio.Lock, creating it lazily.

        Lazy initialization is required because `asyncio.Lock()` raises
        `RuntimeError: no running event loop` if constructed outside a loop.
        The double-check pattern handles concurrent first-touch (e.g. from
        multiple threads in tests); for in-loop first-touch the GIL plus
        the single-attribute write is sufficient.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def append(self, event: Event) -> None:
        """Append one event while serializing writes to the JSONL log."""
        line = event.model_dump_json()
        async with self._get_lock():
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
