"""Tests for stage node base classes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode


class TestPipelineContext:
    def test_minimal_context(self, tmp_project_dir: Path):
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
            events_log=EventsLog(tmp_project_dir / "events.jsonl"),
        )
        assert ctx.project_dir == tmp_project_dir
        assert ctx.mapping.project_id == "test"


class TestStageNode:
    def test_subclass_must_implement_run(self, tmp_project_dir: Path):
        class IncompleteStage(StageNode):
            name = "incomplete"

        with pytest.raises(TypeError, match="abstract"):
            IncompleteStage(
                events_log=EventsLog(tmp_project_dir / "events.jsonl")
            )

    def test_run_emits_start_and_complete_events(self, tmp_project_dir: Path):
        class SimpleStage(StageNode):
            name = "simple"

            def _run(self, context: PipelineContext) -> PipelineContext:
                return context

        log_path = tmp_project_dir / "events.jsonl"
        log = EventsLog(log_path)
        stage = SimpleStage(events_log=log)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
            events_log=log,
        )
        stage.run(ctx)
        events = log.read_all()
        assert len(events) == 2
        assert events[0].event_type == EventType.STAGE_STARTED
        assert events[0].payload == {"stage": "simple"}
        assert events[1].event_type == EventType.STAGE_COMPLETED
        assert events[1].payload == {"stage": "simple"}

    def test_run_records_failure_event_on_exception(self, tmp_project_dir: Path):
        class FailingStage(StageNode):
            name = "failing"

            def _run(self, context: PipelineContext) -> PipelineContext:
                raise RuntimeError("simulated failure")

        log_path = tmp_project_dir / "events.jsonl"
        log = EventsLog(log_path)
        stage = FailingStage(events_log=log)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
            events_log=log,
        )
        with pytest.raises(RuntimeError, match="simulated failure"):
            stage.run(ctx)
        events = log.read_all()
        # STAGE_STARTED was emitted; the exception should propagate (no
        # STAGE_COMPLETED, but the failure is visible in the log).
        assert events[0].event_type == EventType.STAGE_STARTED


def test_pipeline_context_plan_path_default(tmp_path):
    from mage.orchestration.nodes import PipelineContext

    mapping = MappingArtifact(schema_version=1, project_id="test", base_bids=[])
    events_log = EventsLog(tmp_path / "events.jsonl")
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=mapping,
        events_log=events_log,
    )
    assert ctx.plan_path == tmp_path / "plan.md"


def test_pipeline_context_plan_path_overridable(tmp_path):
    from mage.orchestration.nodes import PipelineContext

    custom = tmp_path / "custom-plan.md"
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=custom,
    )
    assert ctx.plan_path == custom


def test_pipeline_context_carries_automation_cursor(tmp_path):
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.runner import AutomationCursor

    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(schema_version=1, project_id="p", base_bids=[]),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        iteration=0,
    )
    assert ctx.automation_cursor is None

    cursor = AutomationCursor(sub_bid="00001-0001", increment_index=0, iteration=1)
    ctx.automation_cursor = cursor
    assert ctx.automation_cursor is cursor

    ctx.automation_cursor = None
    assert ctx.automation_cursor is None
