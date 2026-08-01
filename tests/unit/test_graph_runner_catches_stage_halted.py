"""Unit tests for the graph runner's StageHalted catch."""

from __future__ import annotations

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.exceptions import StageHalted
from mage.orchestration.graph import PipelineGraph
from mage.orchestration.nodes import PipelineContext, StageNode


class HaltStage(StageNode):
    name = "halt_stage"

    async def _run(self, context: PipelineContext) -> PipelineContext:
        raise StageHalted(
            reason="plan_approval",
            feature_id="feat-001",
            plan_digest="abc",
        )


@pytest.mark.asyncio
async def test_graph_runner_catches_stage_halted_emits_halt_persisted(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    graph = PipelineGraph(stages=[HaltStage(log)], events_log=log)
    with pytest.raises(SystemExit) as exc_info:
        await graph.run(ctx)
    assert exc_info.value.code == 0

    events = log.read_all()
    halt_events = [e for e in events if e.event_type == EventType.HALT_PERSISTED]
    assert len(halt_events) == 1
    assert halt_events[0].payload["reason"] == "plan_approval"
    assert halt_events[0].payload["originating_stage"] == "decomposition"
    assert halt_events[0].payload["affected_behaviors"] == []
