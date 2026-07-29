"""Tests for the Pydantic-Graph skeleton."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.graph import PipelineGraph
from mage.orchestration.nodes import PipelineContext, StageNode


class IncrementingStage(StageNode):
    """A trivial stage that increments context.iteration."""

    name = "increment"

    def _run(self, context: PipelineContext) -> PipelineContext:
        return context.model_copy(update={"iteration": context.iteration + 1})


class TaggingStage(StageNode):
    """A trivial stage that tags the current stage."""

    name = "tag"

    def _run(self, context: PipelineContext) -> PipelineContext:
        return context.model_copy(update={"current_stage": "tagged"})


class TestPipelineGraph:
    def test_runs_stages_in_order(self, tmp_project_dir: Path):
        log = EventsLog(tmp_project_dir / "events.jsonl")
        graph = PipelineGraph(
            stages=[IncrementingStage(events_log=log), IncrementingStage(events_log=log)],
            events_log=log,
        )
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
            events_log=log,
        )
        result = graph.run(ctx)
        assert result.iteration == 2

    def test_emits_events_for_each_stage(self, tmp_project_dir: Path):
        log = EventsLog(tmp_project_dir / "events.jsonl")
        graph = PipelineGraph(
            stages=[IncrementingStage(events_log=log), TaggingStage(events_log=log)],
            events_log=log,
        )
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
            events_log=log,
        )
        graph.run(ctx)
        events = log.read_all()
        # Two stages × two events each = 4 events
        assert len(events) == 4
        started = [e for e in events if e.event_type == EventType.STAGE_STARTED]
        completed = [e for e in events if e.event_type == EventType.STAGE_COMPLETED]
        assert len(started) == 2
        assert len(completed) == 2
        assert {e.payload["stage"] for e in started} == {"increment", "tag"}

    def test_empty_stages_returns_context_unchanged(self, tmp_project_dir: Path):
        log = EventsLog(tmp_project_dir / "events.jsonl")
        graph = PipelineGraph(stages=[], events_log=log)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
            events_log=log,
        )
        result = graph.run(ctx)
        assert result.iteration == 0


def test_pipeline_graph_catches_plan_revision_required_and_halts(tmp_path):
    from mage.artifacts.plan import PlanRevisionRequired
    from mage.orchestration.events import EventsLog, EventType
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.nodes import PipelineContext, StageNode

    log = EventsLog(tmp_path / "events.jsonl")

    class HaltingStage(StageNode):
        name = "halting"
        def _run(self, context):
            raise PlanRevisionRequired(
                reason="Plan ordering is wrong",
                originating_stage="halting",
                affected_behaviors=["00000"],
            )

    class NeverRunStage(StageNode):
        name = "never"
        def _run(self, context):
            raise AssertionError("should not run")

    graph = PipelineGraph(
        stages=[HaltingStage(log), NeverRunStage(log)],
        events_log=log,
    )

    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
        events_log=log,
    )

    with pytest.raises(SystemExit) as exc_info:
        graph.run(ctx)
    assert exc_info.value.code == 0

    halt_events = [e for e in log.read_all() if e.event_type == EventType.HALT_PERSISTED]
    assert len(halt_events) == 1
    assert halt_events[0].payload["reason"] == "Plan ordering is wrong"
    assert halt_events[0].payload["originating_stage"] == "halting"


def test_pipeline_graph_catches_review_budget_exhausted_and_halts(tmp_path):
    """I1: ReviewBudgetExhausted raised by InscribeStage is caught by the
    graph; the graph exits cleanly (SystemExit 0) without re-raising.
    """
    from mage.orchestration.events import EventsLog
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.inscribe import ReviewBudgetExhausted
    from mage.orchestration.nodes import PipelineContext, StageNode

    log = EventsLog(tmp_path / "events.jsonl")

    class BudgetExhaustedStage(StageNode):
        name = "budget_exhausted"
        def _run(self, context):
            raise ReviewBudgetExhausted(
                base_bid="00000", scenario_name="authenticate-user", iteration=3,
            )

    class NeverRunStage(StageNode):
        name = "never"
        def _run(self, context):
            raise AssertionError("should not run after halt")

    graph = PipelineGraph(
        stages=[BudgetExhaustedStage(log), NeverRunStage(log)],
        events_log=log,
    )

    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
        events_log=log,
    )

    with pytest.raises(SystemExit) as exc_info:
        graph.run(ctx)
    assert exc_info.value.code == 0


class TestPlan4HaltCatching:
    def test_graph_catches_scenario_inspect_halted(self, tmp_path):
        """Plan 6: graph catches ScenarioInspectHalted, persists the mapping
        with feature_status='halted', and emits HALT_PERSISTED.
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise ScenarioInspectHalted(
                    "spec-route finding for sub-bid 00000-0"
                )

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)

        with pytest.raises(SystemExit):
            graph.run(ctx)

        saved_mapping = MappingArtifact.load(tmp_path / "mapping.yaml")
        assert saved_mapping.feature_status == "halted"

    def test_graph_updates_in_memory_mapping_after_halt(self, tmp_path):
        """Plan 6: subsequent stages in the same graph run do not execute
        after a halt (graph exits via SystemExit before reaching them).
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")

        later_stage_ran = []

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise ScenarioInspectHalted(
                    "spec-route finding for sub-bid 00000-0"
                )

        class LaterStage(StageNode):
            name = "later"

            def _run(self, context):
                later_stage_ran.append(True)
                return context

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(
            stages=[HaltStage(log), LaterStage(log)],
            events_log=log,
        )
        with pytest.raises(SystemExit):
            graph.run(ctx)
        assert later_stage_ran == []
        assert ctx.mapping.feature_status == "halted"

    def test_graph_skips_persist_when_project_dir_missing(self, tmp_path):
        """Plan 6: guard the persistence step. If project_dir does not
        exist, the graph still updates the in-memory mapping without
        crashing trying to save.
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")
        missing_dir = tmp_path / "does-not-exist"

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise ScenarioInspectHalted(
                    "spec-route finding for sub-bid 00000-0"
                )

        ctx = PipelineContext(
            project_dir=missing_dir,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
        with pytest.raises(SystemExit):
            graph.run(ctx)
        # In-memory mapping still updated.
        assert ctx.mapping.feature_status == "halted"
        # On-disk mapping was NOT created (we skipped the save).
        assert not (missing_dir / "mapping.yaml").exists()

    def test_graph_emits_at_most_one_halt_event_per_halt(self, tmp_path):
        """Plan 6: InspectLoopStage returns the "spec" route; the runner
        (or its graph shim) translates that into ScenarioInspectHalted, and
        the graph emits exactly one HALT_PERSISTED event for that halt
        (Critical 2 dedupe lives at the graph layer now).
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext, StageNode
        from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class AlwaysPassMech:
            def verify(self, scope):
                return []

        finding = ReviewerFinding(
            id="f-spec",
            severity="major",
            location="src/foo.py",
            issue="Spec is wrong",
            rationale="Scenario describes the wrong thing",
            suggestion="spec:Halt",
            route="spec",
        )

        class SpecReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                return ReviewerVerdict(
                    dimension="increment_quality",
                    outcome="fail",
                    draft_hash="",
                    reviewed_at=datetime.now(UTC),
                    reviewer_id="increment_quality@v1",
                    findings=[finding],
                )

        # Drive InspectLoopStage via a StageNode shim that mirrors what
        # FeatureRunner does: a "spec" route from inspect_increment becomes
        # ScenarioInspectHalted, which the graph then catches.
        class InspectStage(StageNode):
            name = "inspect-loop"

            def __init__(self, events_log, inspect_loop_stage, target, increment, result):
                super().__init__(events_log)
                self.inspect_loop_stage = inspect_loop_stage
                self.target = target
                self.increment = increment
                self.result = result

            def _run(self, context):
                route = self.inspect_loop_stage.inspect_increment(
                    context,
                    target=self.target,
                    increment=self.increment,
                    result=self.result,
                )
                if route == "spec":
                    raise ScenarioInspectHalted(
                        f"spec-route finding for sub-bid {self.target.sub_bid!r}"
                    )
                return context

        inspect_loop = InspectLoopStage(
            log,
            mechanical_verifier=AlwaysPassMech(),
            increment_quality_reviewer=SpecReviewer(),
            host_config=HostConfig(),
        )
        target = ScenarioTarget(
            base_bid="00000",
            sub_bid="00000-0",
            scenario_name="happy",
            gherkin_body="",
            steps=[],
        )
        increment = Increment(
            index=0, step="seed", red_test_path="t.py", red_test_code=""
        )
        result = IncrementResult(files_changed=[], summary="", diff="")

        graph = PipelineGraph(
            stages=[InspectStage(log, inspect_loop, target, increment, result)],
            events_log=log,
        )

        with pytest.raises(SystemExit):
            graph.run(ctx)

        halt_events = [
            event for event in log.read_all()
            if event.event_type.value == "halt_persisted"
        ]
        assert len(halt_events) == 1, (
            f"expected exactly 1 HALT_PERSISTED, got {len(halt_events)}"
        )
        # Graph-level halt persistence records the exception message as the reason.
        reason = halt_events[0].payload.get("reason") or ""
        assert "00000-0" in reason

    def test_graph_run_method_invokes_catch_handler(self, tmp_path):
        """Sanity: PipelineGraph.run() catches ScenarioInspectHalted and
        exits cleanly (SystemExit 0) without re-raising.
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise ScenarioInspectHalted(
                    "spec-route finding for sub-bid 00000-0"
                )

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
        with pytest.raises(SystemExit) as exc_info:
            graph.run(ctx)
        assert exc_info.value.code == 0
        assert ctx.mapping.feature_status == "halted"

    def test_inspect_loop_stage_is_not_a_stage_node(self):
        """Plan 6: InspectLoopStage is driven by FeatureRunner, not the
        linear graph. It is intentionally NOT a `StageNode` subclass — passing
        it directly to `PipelineGraph` must fail loudly rather than be
        silently mis-wired.
        """
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import StageNode

        assert not issubclass(InspectLoopStage, StageNode), (
            "InspectLoopStage must not inherit from StageNode; Plan 6 drives "
            "it via FeatureRunner, not the linear graph runner."
        )


class TestPlan5HaltCatching:
    def test_inspect_feature_halt_persists_once_and_terminates_graph(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import Event, EventsLog, EventType
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.inspect_feature import InspectFeatureHalted
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")
        later_stage_ran = []

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.INSPECT_FEATURE_HALT_PERSISTED,
                        payload={"feature_id": "feat-1", "iteration": 3},
                    )
                )
                raise InspectFeatureHalted(feature_id="feat-1", iteration=3)

        class LaterStage(StageNode):
            name = "later-stage"

            def _run(self, context):
                later_stage_ran.append(True)
                return context

        context = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(
            stages=[HaltStage(log), LaterStage(log)],
            events_log=log,
        )

        with pytest.raises(SystemExit) as exc_info:
            graph.run(context)

        assert exc_info.value.code == 0
        assert later_stage_ran == []
        assert context.mapping.feature_status == "halted"
        assert MappingArtifact.load(tmp_path / "mapping.yaml").feature_status == "halted"
        halt_events = [
            event
            for event in log.read_all()
            if event.event_type.value == "inspect_feature_halt_persisted"
        ]
        assert len(halt_events) == 1


def test_graph_stops_on_scenario_inspect_halted(tmp_path):
    """GC-10: ScenarioInspectHalted now shares the halt-persistence path
    with the other halt types. The graph must raise SystemExit(0), persist
    the mapping as 'halted', and persist halt state — preventing later
    stages (InspectFeature, Settle) from running against a feature whose
    scenarios are not all live.
    """
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.etch import ScenarioInspectHalted
    from mage.orchestration.events import EventsLog
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.nodes import PipelineContext, StageNode
    from mage.orchestration.persistence import FileStatePersistence

    class _HaltStage(StageNode):
        name = "halt_stage"

        def _run(self, context):
            raise ScenarioInspectHalted("spec finding")

    class _Dummy(StageNode):
        name = "dummy"

        def _run(self, context):
            return context

    log = EventsLog(tmp_path / "events.jsonl")
    graph = PipelineGraph(stages=[_HaltStage(log), _Dummy(log)], events_log=log)
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=log,
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )
    with pytest.raises(SystemExit):
        graph.run(ctx)
    # Mapping was persisted as halted.
    saved = MappingArtifact.load(tmp_path / "mapping.yaml")
    assert saved.feature_status == "halted"
    # State was persisted.
    state = FileStatePersistence(
        state_dir=tmp_path / ".haileris" / "state",
        state_type=PipelineContext,
    ).load_state()
    assert state is not None
