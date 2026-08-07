"""Unit test for Plan 29 — empty-steps audit-trail closure in EtchStage.

P29 closes the P26 Minor finding at etch.py:71: when `target.steps` is
empty, the for-loop never executes, no ETCH_COMPLETED is recorded, and
the function returns [] without any audit-trail entry. The fix adds a
final ETCH_COMPLETED emit after the loop, regardless of whether any
iterations ran.

Note: StageNode._emit injects {"stage": self.name} into every emitted
event; this test uses key-by-key access (per the P28a convention) to
avoid coupling to the injected stage key.
"""

from __future__ import annotations

import pytest

from mage.agents.etch import EtchAgent, RedTestSpec
from mage.orchestration.etch import EtchStage
from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.runner import ScenarioTarget


class _NoOpAgent(EtchAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    async def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        self.calls.append((step, scenario_context))
        raise AssertionError("agent.run should not be called when steps is empty")


def _context(tmp_path):
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.nodes import PipelineContext

    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


@pytest.mark.asyncio
async def test_run_scenario_with_empty_steps_emits_final_completion(tmp_path):
    ctx = _context(tmp_path)
    agent = _NoOpAgent()
    stage = EtchStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=[],
    )

    increments = await stage.run_scenario(ctx, target)

    assert increments == []
    types = [e.event_type for e in ctx.events_log.read_all()]
    assert types.count(EventType.ETCH_STARTED) == 1
    # No per-step emits because the loop never ran.
    assert types.count(EventType.ETCH_RED_CONFIRMED) == 0
    # One final ETCH_COMPLETED closes the audit trail.
    assert types.count(EventType.ETCH_COMPLETED) == 1
    final = next(
        e for e in ctx.events_log.read_all() if e.event_type == EventType.ETCH_COMPLETED
    )
    assert final.payload["red_test_count"] == 0
    assert final.payload["reason"] == "no_steps"
    assert final.payload["scenario_name"] == "happy"
