"""Tests for the Pydantic-Graph skeleton."""

from __future__ import annotations

from pathlib import Path

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventType, EventsLog
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
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.nodes import PipelineContext, StageNode
    from mage.orchestration.events import EventsLog, EventType
    from mage.artifacts.plan import PlanRevisionRequired

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
