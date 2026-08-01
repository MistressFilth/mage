"""PipelineGraph: linear stage runner with halt handling."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.artifacts.mapping import LifecycleStatus
from mage.artifacts.plan import PlanRevisionRequired
from mage.orchestration.discipline.policy import (
    assert_decomposition_closed,
    assert_independent_gates,
)
from mage.orchestration.discipline.stage import DisciplineStage
from mage.orchestration.etch import ScenarioInspectHalted
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.exceptions import StageHalted
from mage.orchestration.inspect_feature import InspectFeatureHalted
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.persistence import FileStatePersistence


class PipelineGraph:
    """Runs a list of stages in order, threading PipelineContext through them."""

    def __init__(self, stages: list[StageNode], events_log: EventsLog) -> None:
        self.events_log = events_log
        self.stages = list(stages)

    async def run(self, initial_context: PipelineContext) -> PipelineContext:
        """Run the graph asynchronously, threading context through stages.

        The graph remains linear; the async surface allows stages to coordinate
        their own concurrent work while preserving stage order.
        """
        # I1: lazy-import the InscribeStage exception to avoid a circular import
        # (inscribe.py imports from orchestration.nodes; graph.py lives alongside).
        from mage.orchestration.inscribe import ReviewBudgetExhausted

        context = initial_context
        discipline = DisciplineStage(self.events_log)
        last_seen_count = len(self.events_log.read_all())
        # Plan 7: P4 (decomposition closed) + P1 (per-scenario independence)
        # are enforced at pipeline start. Both are per-scenario-cycle gates:
        # they only apply when the mapping carries scenarios that are not
        # already in a terminal state. A fresh mapping (no base_bids, or all
        # scenarios LIVE/DEPRECATED/RETIRED) has nothing to gate, so the
        # check is a no-op. This keeps the call safe for graph-infrastructure
        # tests that drive a pipeline without a finalized plan.
        _active_statuses = {
            LifecycleStatus.INSCRIBING,
            LifecycleStatus.APPROVED,
        }
        _has_active = any(
            s.lifecycle_status in _active_statuses
            for entry in context.mapping.base_bids
            for s in entry.scenarios
        )
        if _has_active:
            # plan_path is optional in the context; the check requires a path.
            # If unset, treat as "no plan" and let the assertion surface the
            # missing path on its own.
            assert context.plan_path is not None
            assert_decomposition_closed(context.plan_path, context.events_log)
            for entry in context.mapping.base_bids:
                for scenario in entry.scenarios:
                    assert_independent_gates(context.mapping, scenario.sub_bid)
        for stage in self.stages:
            try:
                context = await stage.run(context)
                last_seen_count = await self._dispatch_new_events(
                    context, discipline, last_seen_count
                )
            except ScenarioInspectHalted as e:
                # All halts now share the persistence path. The graph stops
                # cleanly so a feature halt (or any other halt) cannot leak
                # into a later stage.
                context.mapping = context.mapping.model_copy(
                    update={"feature_status": "halted"}
                )
                if context.project_dir is not None and context.project_dir.exists():
                    await context.mapping.save(context.project_dir / "mapping.yaml")
                await self._persist_halt(context, e)
                last_seen_count = await self._dispatch_new_events(
                    context, discipline, last_seen_count
                )
                raise SystemExit(0) from e
            except InspectFeatureHalted as e:
                # InspectFeatureStage is the sole owner of the halt event. The
                # graph persists the coarse lifecycle state and terminates so
                # Settle or any later stage cannot run after a feature halt.
                context.mapping = context.mapping.model_copy(
                    update={"feature_status": "halted"}
                )
                if context.project_dir is not None and context.project_dir.exists():
                    await context.mapping.save(context.project_dir / "mapping.yaml")
                last_seen_count = await self._dispatch_new_events(
                    context, discipline, last_seen_count
                )
                raise SystemExit(0) from e
            except ReviewBudgetExhausted as e:
                # I1: review-budget halts the same way as plan-revision halts.
                # The InscribeStage already emitted REVIEW_HALT_PERSISTED and
                # the halt is visible in the events log; we just need to stop
                # the graph cleanly.
                last_seen_count = await self._dispatch_new_events(
                    context, discipline, last_seen_count
                )
                raise SystemExit(0) from e
            except PlanRevisionRequired as e:
                await self._persist_halt(context, e)
                last_seen_count = await self._dispatch_new_events(
                    context, discipline, last_seen_count
                )
                raise SystemExit(0) from e
            except StageHalted as e:
                # Plan 15 approval gate halt. Emit HALT_PERSISTED with the
                # carried reason, save mapping in halted state, exit cleanly.
                # No .haileris/state write — the marker file is the persistence.
                context.mapping = context.mapping.model_copy(
                    update={"feature_status": "halted"}
                )
                if context.project_dir is not None and context.project_dir.exists():
                    await context.mapping.save(context.project_dir / "mapping.yaml")
                halt_event = Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.HALT_PERSISTED,
                    payload={
                        "reason": e.reason,
                        "originating_stage": e.originating_stage,
                        "affected_behaviors": e.affected_behaviors,
                        "context_snapshot": {**e.context, "stage": stage.name},
                    },
                )
                await context.events_log.append(halt_event)
                last_seen_count = await self._dispatch_new_events(
                    context, discipline, last_seen_count
                )
                raise SystemExit(0) from e
        return context

    async def _dispatch_new_events(
        self,
        context: PipelineContext,
        discipline: DisciplineStage,
        last_seen_count: int,
    ) -> int:
        """Send events emitted since the previous stage to DisciplineStage."""
        current_events = self.events_log.read_all()
        for event in current_events[last_seen_count:]:
            await discipline._handle_event(context, event)
        return len(current_events)

    async def _persist_halt(
        self, context: PipelineContext, halt: BaseException
    ) -> None:
        """Persist halt record (event + state).

        PlanRevisionRequired carries structured fields (reason,
        originating_stage, affected_behaviors). ScenarioInspectHalted carries
        only a message string. Use getattr with defaults so both flow
        through the same persist path.
        """
        reason = getattr(halt, "reason", None)
        if reason is None:
            reason = str(halt) or halt.__class__.__name__
        originating_stage = (
            getattr(halt, "originating_stage", None) or "scenario_inspect"
        )
        affected_behaviors = getattr(halt, "affected_behaviors", None) or []
        halt_event = Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.HALT_PERSISTED,
            payload={
                "reason": reason,
                "originating_stage": originating_stage,
                "affected_behaviors": affected_behaviors,
                "context_snapshot": context.model_dump(mode="json"),
            },
        )
        await context.events_log.append(halt_event)

        state_dir = context.project_dir / ".haileris" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        persistence = FileStatePersistence(
            state_dir=state_dir, state_type=PipelineContext
        )
        persistence.save_state(context)
