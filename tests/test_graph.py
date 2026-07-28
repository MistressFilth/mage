"""Tests for the Pydantic-Graph skeleton."""

from __future__ import annotations

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
        halt_events = [
            event
            for event in log.read_all()
            if event.event_type.value == "scenario_halt_persisted"
        ]
        assert len(halt_events) == 1
        assert halt_events[0].payload == {
            "base_bid": "00000",
            "scenario_name": "happy",
            "sub_bid": "00000-0",
            "iteration": 8,
        }
        saved_mapping = MappingArtifact.load(tmp_path / "mapping.yaml")
        assert saved_mapping.feature_status == "inspect_pending"
