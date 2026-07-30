"""Tests for EtchStage.run_scenario."""

from __future__ import annotations

import pytest

from mage.agents.etch import EtchAgent, RedTestSpec
from mage.orchestration.etch import EtchStage
from mage.orchestration.events import EventsLog
from mage.orchestration.runner import ScenarioTarget


class _StubAgent(EtchAgent):
    """A trivial EtchAgent subclass used in tests."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    async def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        self.calls.append((step, scenario_context))
        return RedTestSpec(
            step_name=step,
            test_path=f"tests/{step}.py",
            test_code=f"def test_{step}(): pass\n",
        )


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
async def test_run_scenario_emits_one_increment_per_step(tmp_path):
    ctx = _context(tmp_path)
    agent = _StubAgent()
    stage = EtchStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed", "grow", "harvest"],
    )

    increments = await stage.run_scenario(ctx, target)

    assert [inc.index for inc in increments] == [0, 1, 2]
    assert [inc.step for inc in increments] == ["seed", "grow", "harvest"]
    assert [inc.red_test_path for inc in increments] == [
        "tests/seed.py",
        "tests/grow.py",
        "tests/harvest.py",
    ]
    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert types.count("etch_started") == 1
    assert types.count("etch_red_confirmed") == 3
    assert types.count("etch_completed") == 3


@pytest.mark.asyncio
async def test_run_scenario_passes_target_sub_bid_to_agent(tmp_path):
    ctx = _context(tmp_path)
    agent = _StubAgent()
    stage = EtchStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["only"],
    )

    await stage.run_scenario(ctx, target)

    assert agent.calls == [("only", {"sub_bid": "00001-0001"})]


@pytest.mark.asyncio
async def test_etch_stage_uses_pydantic_agent_when_model_set(tmp_path):
    """When HostConfig.model is set, EtchStage.__init__ swaps stub for PydanticEtchAgent."""
    from mage.agents.etch import PydanticEtchAgent
    from mage.verification.host_overrides import HostConfig

    ctx = _context(tmp_path)
    host_config = HostConfig(model="test")
    stage = EtchStage(
        ctx.events_log,
        agent=_StubAgent(),
        host_config=host_config,
    )
    assert isinstance(stage.agent, PydanticEtchAgent), (
        "EtchStage should swap the stub for PydanticEtchAgent when model is set"
    )


@pytest.mark.asyncio
async def test_etch_stage_keeps_stub_when_no_model_set(tmp_path):
    """When HostConfig.model is unset, EtchStage preserves the injected stub."""
    from mage.verification.host_overrides import HostConfig

    ctx = _context(tmp_path)
    host_config = HostConfig()
    stage = EtchStage(
        ctx.events_log,
        agent=_StubAgent(),
        host_config=host_config,
    )
    assert isinstance(stage.agent, _StubAgent), (
        "EtchStage must not swap when no model is set"
    )