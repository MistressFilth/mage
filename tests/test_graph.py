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
        """Critical 1 + Critical 2: graph catches the exception, updates
        in-memory mapping to 'inspect_pending', and persists it — but does
        NOT emit a second SCENARIO_HALT_PERSISTED event (InspectLoopStage is
        the sole owner of that event).
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
                    base_bid="00000",
                    scenario_name="happy",
                    sub_bid="00000-0",
                    iteration=8,
                )

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
        result = graph.run(ctx)

        assert result is not None
        # Critical 2 fix: the graph does NOT emit SCENARIO_HALT_PERSISTED —
        # InspectLoopStage is the sole owner. Test that the HALT event is
        # absent here (this test stage raises without first emitting).
        halt_events = [
            event
            for event in log.read_all()
            if event.event_type.value == "scenario_halt_persisted"
        ]
        assert len(halt_events) == 0, (
            "graph handler must not emit SCENARIO_HALT_PERSISTED; "
            f"got {len(halt_events)} event(s)"
        )
        saved_mapping = MappingArtifact.load(tmp_path / "mapping.yaml")
        assert saved_mapping.feature_status == "inspect_pending"

    def test_graph_updates_in_memory_mapping_after_halt(self, tmp_path):
        """Critical 1: subsequent stages in the same graph run must observe
        the updated in-memory mapping (feature_status='inspect_pending').
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")

        observed_status: list[str] = []

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise ScenarioInspectHalted(
                    base_bid="00000",
                    scenario_name="happy",
                    sub_bid="00000-0",
                    iteration=8,
                )

        class ObserveAfterHaltStage(StageNode):
            name = "observe"

            def _run(self, context):
                observed_status.append(context.mapping.feature_status)
                return context

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(
            stages=[HaltStage(log), ObserveAfterHaltStage(log)],
            events_log=log,
        )
        # The graph must NOT re-raise (it handles the halt cleanly), and the
        # follow-up stage must see the updated mapping.
        graph.run(ctx)
        assert observed_status == ["inspect_pending"], (
            f"follow-up stage saw status {observed_status!r}, "
            "expected ['inspect_pending']"
        )

    def test_graph_skips_persist_when_project_dir_missing(self, tmp_path):
        """Critical 1: guard the persistence step. If project_dir does not
        exist (e.g., test fixture constructs PipelineContext with a missing
        path), the graph must still update the in-memory mapping without
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
                    base_bid="00000",
                    scenario_name="happy",
                    sub_bid="00000-0",
                    iteration=8,
                )

        ctx = PipelineContext(
            project_dir=missing_dir,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
        # Must not raise — guard prevents the missing-dir save from blowing up.
        result = graph.run(ctx)
        # In-memory mapping still updated.
        assert result.mapping.feature_status == "inspect_pending"
        # On-disk mapping was NOT created (we skipped the save).
        assert not (missing_dir / "mapping.yaml").exists()

    def test_graph_emits_at_most_one_halt_event_per_halt(self, tmp_path):
        """Critical 2 canonical regression test.

        Drive InspectLoopStage._run_single_increment (the real entry point —
        the graph-driven `_run` raises NotImplementedError per Minor 6) with a
        spec-route reviewer that emits the event before raising. Wrap the
        call in the same try/except the graph uses (delegated helper) and
        assert exactly 1 SCENARIO_HALT_PERSISTED event is observable.
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
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

        inspect_stage = InspectLoopStage(
            log, AlwaysPassMech(), SpecReviewer(), HostConfig()
        )

        # Simulate the graph's halt-handling path explicitly: catch the
        # exception (graph handlers don't re-raise; they update mapping +
        # optionally save). We replicate the in-memory update here so we can
        # confirm exactly 1 event was emitted (graph-level emission was
        # removed in Critical 2).
        try:
            inspect_stage._run_single_increment(
                ctx,
                sub_bid="00000-0",
                increment_diff="",
                new_test="",
                scenario_steps=[],
            )
        except ScenarioInspectHalted:
            # Mirror the graph handler's in-memory mapping update.
            ctx.mapping = ctx.mapping.model_copy(
                update={"feature_status": "inspect_pending"}
            )

        halt_events = [
            event for event in log.read_all()
            if event.event_type.value == "scenario_halt_persisted"
        ]
        assert len(halt_events) == 1, (
            f"expected exactly 1 SCENARIO_HALT_PERSISTED, got {len(halt_events)}"
        )
        # The single event is the one emitted by InspectLoopStage (it carries
        # the 'reason' field; verify that here to prove provenance).
        assert halt_events[0].payload.get("reason") == "spec_route_finding"

    def test_graph_run_method_invokes_catch_handler(self, tmp_path):
        """Sanity: PipelineGraph.run() catches ScenarioInspectHalted and
        returns the (updated) context without re-raising. This is the
        canonical flow the Critical 2 dedupe relies on.
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
                    base_bid="00000",
                    scenario_name="happy",
                    sub_bid="00000-0",
                    iteration=8,
                )

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
        # The graph handles the halt cleanly — no re-raise.
        result = graph.run(ctx)
        # In-memory mapping was updated (Critical 1 fix).
        assert result.mapping.feature_status == "inspect_pending"

    def test_run_method_raises_not_implemented_for_inspect_loop_stage(self, tmp_path):
        """Minor 6: InspectLoopStage._run is no longer a silent stub. The
        graph-runner calling `_run` directly should now raise loudly rather
        than emit a false INSPECT_LOOP_COMPLETED event.
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class CleanMech:
            def verify(self, scope):
                return []

        class CleanReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                return ReviewerVerdict(
                    dimension="increment_quality",
                    outcome="pass",
                    draft_hash="",
                    reviewed_at=datetime.now(UTC),
                    reviewer_id="increment_quality@v1",
                    findings=[],
                )

        inspect_stage = InspectLoopStage(
            log, CleanMech(), CleanReviewer(), HostConfig()
        )
        graph = PipelineGraph(stages=[inspect_stage], events_log=log)
        with pytest.raises(NotImplementedError):
            graph.run(ctx)
        # No false INSPECT_LOOP_COMPLETED event was emitted.
        types = [e.event_type.value for e in log.read_all()]
        assert "inspect_loop_completed" not in types


class TestPlan5HaltCatching:
    def test_graph_catches_inspect_feature_halted(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.inspect_feature import InspectFeatureHalted
        from mage.orchestration.nodes import PipelineContext, StageNode

        log = EventsLog(tmp_path / "events.jsonl")

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise InspectFeatureHalted(feature_id="feat-1", iteration=3)

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
        graph.run(ctx)

        events = log.read_all()
        halt_events = [
            e for e in events
            if e.event_type.value == "inspect_feature_halt_persisted"
        ]
        assert len(halt_events) == 1
        assert halt_events[0].payload["feature_id"] == "feat-1"
        assert halt_events[0].payload["iteration"] == 3
