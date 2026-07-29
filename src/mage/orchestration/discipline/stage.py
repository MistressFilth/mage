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
        emissions of the same event for the same scenario.
        """
        et = event.event_type
        payload = event.payload

        if et == EventType.SCENARIO_APPROVED:
            release_cycle_lock(context)
            return

        if et == EventType.SCENARIO_REVISION_REQUESTED:
            sub_bid = payload["sub_bid"]
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
            context.mapping = begin_supersession(
                mapping=context.mapping,
                old_sub_bid=payload["old_sub_bid"],
                new_sub_bid=payload["new_sub_bid"],
                reason=payload.get("reason", ""),
                timestamp=event.timestamp,
            )
            return

        if et == EventType.SCENARIO_LIVE:
            new_sub_bid = payload.get("sub_bid")
            if new_sub_bid is None:
                return
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
