"""PipelineGraph: linear stage runner with halt handling."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.artifacts.plan import PlanRevisionRequired
from mage.orchestration.etch import ScenarioInspectHalted
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.inspect_feature import InspectFeatureHalted
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
        # I1: lazy-import the InscribeStage exception to avoid a circular import
        # (inscribe.py imports from orchestration.nodes; graph.py lives alongside).
        from mage.orchestration.inscribe import ReviewBudgetExhausted

        context = initial_context
        for stage in self.stages:
            try:
                context = stage.run(context)
            except ScenarioInspectHalted:
                # CRITICAL 1: Update in-memory mapping so subsequent stages in
                # this same graph run observe the inspect_pending status.
                # CRITICAL 2: InspectLoopStage is the SOLE owner of the
                # SCENARIO_HALT_PERSISTED event; we don't re-emit it here.
                context.mapping = context.mapping.model_copy(
                    update={"feature_status": "inspect_pending"}
                )
                # Guard persistence: only save when project_dir exists so
                # callers can construct a PipelineContext without a real
                # project directory.
                if context.project_dir is not None and context.project_dir.exists():
                    context.mapping.save(context.project_dir / "mapping.yaml")
            except InspectFeatureHalted as e:
                # InspectFeatureStage is the sole owner of the halt event. The
                # graph persists the coarse lifecycle state and terminates so
                # Settle or any later stage cannot run after a feature halt.
                context.mapping = context.mapping.model_copy(
                    update={"feature_status": "halted"}
                )
                if context.project_dir is not None and context.project_dir.exists():
                    context.mapping.save(context.project_dir / "mapping.yaml")
                raise SystemExit(0) from e
            except ReviewBudgetExhausted as e:
                # I1: review-budget halts the same way as plan-revision halts.
                # The InscribeStage already emitted REVIEW_HALT_PERSISTED and
                # the halt is visible in the events log; we just need to stop
                # the graph cleanly.
                raise SystemExit(0) from e
            except PlanRevisionRequired as e:
                self._persist_halt(context, e)
                raise SystemExit(0) from e
        return context

    def _persist_halt(
        self, context: PipelineContext, halt: PlanRevisionRequired
    ) -> None:
        """Persist halt record (event + state)."""
        halt_event = Event(
            timestamp=datetime.now(UTC),
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