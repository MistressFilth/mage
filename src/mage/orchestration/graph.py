"""PipelineGraph: linear stage runner with halt handling."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mage.artifacts.plan import PlanRevisionRequired
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.persistence import FileStatePersistence

class PipelineGraph:
    """Runs a list of stages in order, threading PipelineContext through them."""

    def __init__(self, stages: list[StageNode], events_log: EventsLog) -> None:
        self.events_log = events_log
        self.stages = list(stages)

    def run(self, initial_context: PipelineContext) -> PipelineContext:
        """Synchronously run the graph, threading context through stages.

        For Plan 1, runs stages directly (not via Pydantic-Graph's async runner).
        Plan 6 will wire in the full async runner for cross-cutting discipline.
        """
        context = initial_context
        for stage in self.stages:
            try:
                context = stage.run(context)
            except PlanRevisionRequired as e:
                self._persist_halt(context, e)
                raise SystemExit(0) from e
        return context

    def _persist_halt(
        self, context: PipelineContext, halt: PlanRevisionRequired
    ) -> None:
        """Persist halt record (event + state)."""
        halt_event = Event(
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.HALT_PERSISTED,
            payload={
                "reason": halt.reason,
                "originating_stage": halt.originating_stage,
                "affected_behaviors": halt.affected_behaviors,
                "context_snapshot": context.model_dump(mode="json"),
            },
        )
        context.events_log.append(halt_event)

        state_dir = context.project_dir / ".haileris" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        persistence = FileStatePersistence(
            state_dir=state_dir, state_type=PipelineContext
        )
        persistence.save_state(context)