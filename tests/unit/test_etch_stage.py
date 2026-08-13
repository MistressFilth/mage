"""Tests for EtchStage.run_scenario."""

from __future__ import annotations

import pytest

from mage.agents.etch import EtchAgent, RedTestSpec
from mage.host_project_config import MageTomlConfig
from mage.orchestration.etch import EtchStage
from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.runner import ScenarioTarget
from mage.providers.config import ProviderConfig


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


def _context(tmp_path, state_store):
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.nodes import PipelineContext

    return PipelineContext(
        state_store=state_store,
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


@pytest.mark.asyncio
async def test_run_scenario_emits_one_increment_per_step(tmp_path, state_store):
    ctx = _context(tmp_path, state_store=state_store)
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
    # 3 per-step ETCH_COMPLETED + 1 final emit after the for-loop (P29).
    assert types.count("etch_completed") == 4


@pytest.mark.asyncio
async def test_run_scenario_passes_target_sub_bid_to_agent(tmp_path, state_store):
    ctx = _context(tmp_path, state_store=state_store)
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
async def test_etch_stage_with_mage_toml_emits_provider_resolved(
    tmp_path, monkeypatch, state_store
):
    """EtchStage constructed with mage_toml must emit PROVIDER_RESOLVED via
    ``flush_pending_events`` so the audit trail records the resolution.

    Finding 2 (P31 final review): when ``__init__`` collects events
    synchronously into ``_pending_provider_events``, the caller (typically
    FeatureRunner) awaits ``flush_pending_events`` before any other event
    emission. The real ``EventsLog.append`` is async, so without the flush
    hook the collected PROVIDER_RESOLVED would be lost.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    providers = {
        "anthropic": ProviderConfig(
            default_model="claude-sonnet-5-20251001",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    }
    mage_toml = MageTomlConfig(default_model="claude-sonnet-5-20251001")
    ctx = _context(tmp_path, state_store=state_store)
    stage = EtchStage(
        ctx.events_log,
        agent=_StubAgent(),
        mage_toml=mage_toml,
        providers=providers,
        default_provider="anthropic",
    )
    # Nothing on disk yet — the constructor collected events into the
    # pending buffer, not onto the async EventsLog.
    assert ctx.events_log.read_all() == []
    # Flushing awaits each collected event against the real log.
    await stage.flush_pending_events()
    events = ctx.events_log.read_all()
    resolved = [e for e in events if e.event_type == EventType.PROVIDER_RESOLVED]
    assert len(resolved) == 1
    assert resolved[0].payload["agent_name"] == "etch"
    assert resolved[0].payload["provider"] == "anthropic"
    assert resolved[0].payload["model_name"] == "claude-sonnet-5-20251001"


@pytest.mark.asyncio
async def test_etch_stage_flush_is_idempotent(tmp_path, monkeypatch, state_store):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    providers = {
        "anthropic": ProviderConfig(
            default_model="claude-sonnet-5-20251001",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    }
    mage_toml = MageTomlConfig(default_model="claude-sonnet-5-20251001")
    ctx = _context(tmp_path, state_store=state_store)
    stage = EtchStage(
        ctx.events_log,
        agent=_StubAgent(),
        mage_toml=mage_toml,
        providers=providers,
        default_provider="anthropic",
    )
    await stage.flush_pending_events()
    first_count = len(ctx.events_log.read_all())
    # Second flush should not re-emit.
    await stage.flush_pending_events()
    second_count = len(ctx.events_log.read_all())
    assert first_count == second_count
