"""DisciplineStage: Pydantic-Graph node that enforces Three Practices.

The stage is event-driven. Existing pipeline stages emit the events listed
below; DisciplineStage reacts. The stage is pure: it mutates context.mapping
through Policy methods and emits audit events. It does not run agents.
"""

from __future__ import annotations

from mage.orchestration.discipline.policy import (
    begin_revision,
    begin_supersession,
    complete_supersession,
    release_cycle_lock,
)
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode


class DisciplineStage(StageNode):
    name = "discipline"

    def __init__(self, events_log: EventsLog) -> None:
        super().__init__(events_log)
        # Per-instance idempotency: a set of (event_type, sub_bid) keys recording
        # which inbound events have already been dispatched. A replayed or
        # re-emitted event for the same scenario is short-circuited so that
        # resume from the events log does not duplicate reversion log entries
        # or audit emissions, nor regress a re-approved scenario back to
        # INSCRIBING.
        self._seen_events: set[tuple[EventType, str]] = set()

    def _run(self, context: PipelineContext) -> PipelineContext:
        """No proactive work — DisciplineStage reacts to events.

        The actual enforcement happens when other stages emit events that this
        stage subscribes to. Pydantic-Graph calls `_run` once per scenario cycle;
        this no-op keeps the stage compatible with the graph shape.
        """
        return context

    def _handle_event(self, context: PipelineContext, event: Event) -> None:
        """Public hook for the orchestrator to invoke on each emitted event.

        Routes events to the matching policy method. Idempotent on repeat
        emissions of the same event for the same scenario: a per-instance set
        keyed by (event_type, sub_bid) records the first dispatch and
        short-circuits subsequent identical dispatches. Resumed or replayed
        event logs therefore neither duplicate reversion log entries nor
        regress a re-approved scenario back to INSCRIBING.

        The SCENARIO_APPROVED handler additionally correlates the cycle-lock
        release to the payload's sub_bid: a stale or delayed approval for a
        different scenario must not clear a lock currently held by another.
        """
        et = event.event_type
        payload = event.payload

        if et == EventType.SCENARIO_APPROVED:
            payload_sub_bid = payload.get("sub_bid") or ""
            key = (et, payload_sub_bid)
            if key in self._seen_events:
                return
            self._seen_events.add(key)
            # Correlate the lock release to the scenario being approved so a
            # stale or delayed SCENARIO_APPROVED does not clear a lock
            # currently held by a different sub_bid. Defensive: if no lock
            # is held, release anyway (no-op on an already-cleared lock).
            if (
                context.current_sub_bid is None
                or context.current_sub_bid == payload_sub_bid
            ):
                release_cycle_lock(context)
            return

        if et == EventType.SCENARIO_REVISION_REQUESTED:
            sub_bid = payload["sub_bid"]
            key = (et, sub_bid)
            if key in self._seen_events:
                return
            self._seen_events.add(key)
            # Defensive: if the scenario isn't in the mapping, this is a
            # synthetic test scenario (e.g., the inspect-loop halt path driven
            # through PipelineGraph with an empty mapping). Skip rather than
            # crash; the event is still recorded in the log for audit.
            if not any(
                s.sub_bid == sub_bid
                for entry in context.mapping.base_bids
                for s in entry.scenarios
            ):
                return
            context.mapping = begin_revision(
                mapping=context.mapping,
                sub_bid=sub_bid,
                reason=payload.get("reason", ""),
                originating_stage=payload.get("originating_stage", "unknown"),
                timestamp=event.timestamp,
            )
            self._emit(EventType.SCENARIO_REVERTED_TO_INSCRIBING, {"sub_bid": sub_bid})
            self._emit(EventType.REVERSION_LOGGED, {"sub_bid": sub_bid})
            return

        if et == EventType.SCENARIO_SUPERSESSION_REQUESTED:
            new_sub_bid = payload["new_sub_bid"]
            key = (et, new_sub_bid)
            if key in self._seen_events:
                return
            self._seen_events.add(key)
            context.mapping = begin_supersession(
                mapping=context.mapping,
                old_sub_bid=payload["old_sub_bid"],
                new_sub_bid=new_sub_bid,
                reason=payload.get("reason", ""),
                timestamp=event.timestamp,
            )
            return

        if et == EventType.SCENARIO_LIVE:
            new_sub_bid = payload.get("sub_bid")
            if new_sub_bid is None:
                return
            key = (et, new_sub_bid)
            if key in self._seen_events:
                return
            self._seen_events.add(key)
            # Check if this scenario supersedes another
            for entry in context.mapping.base_bids:
                for s in entry.scenarios:
                    if s.sub_bid == new_sub_bid and s.supersedes is not None:
                        context.mapping = complete_supersession(
                            mapping=context.mapping,
                            new_sub_bid=new_sub_bid,
                            timestamp=event.timestamp,
                        )
                        self._emit(
                            EventType.SCENARIO_DEPRECATED,
                            {"old_sub_bid": s.supersedes, "new_sub_bid": new_sub_bid},
                        )
                        return
            return
