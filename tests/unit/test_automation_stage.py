"""Tests for AutomationStage."""

from __future__ import annotations

import pytest

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.automation import AutomationStage
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import (
    ScenarioOutcome,
    ScenarioTarget,
)
from mage.verification.host_overrides import HostConfig


def _make_mapping(tmp_path, scenarios: list[ScenarioEntry]) -> MappingArtifact:
    return MappingArtifact(
        schema_version=2,
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00001",
                behavior_name="b",
                behavior_description="d",
                depends_on=[],
                notes="",
                scenarios=scenarios,
            ),
        ],
    )


def _ctx(tmp_path, mapping: MappingArtifact) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=mapping,
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )


def _scenario(sub_bid: str, status: LifecycleStatus) -> ScenarioEntry:
    return ScenarioEntry(
        sub_bid=sub_bid,
        scenario_text_hash=str(hash(sub_bid)),
        lifecycle_status=status,
    )


@pytest.mark.asyncio
async def test_automation_stage_excludes_non_approved_scenarios(tmp_path):
    scenarios = [
        _scenario("00001-0001", LifecycleStatus.APPROVED),
        _scenario("00001-0002", LifecycleStatus.LIVE),  # already done
        _scenario("00001-0003", LifecycleStatus.INSCRIBING),  # not ready
    ]
    mapping = _make_mapping(tmp_path, scenarios)
    ctx = _ctx(tmp_path, mapping)

    captured_targets: list[list[ScenarioTarget]] = []

    class _Runner:
        async def run(self, context, targets, *, cursor=None):
            captured_targets.append(targets)
            return [
                ScenarioOutcome(sub_bid=t.sub_bid, test_paths=["t.py"]) for t in targets
            ]

    stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type, ty:invalid-argument-type]
    await stage.run(ctx)

    sent = captured_targets[0]
    assert [t.sub_bid for t in sent] == ["00001-0001"]


@pytest.mark.asyncio
async def test_automation_stage_writes_back_scenario_outcomes(tmp_path):
    mapping = _make_mapping(
        tmp_path,
        [_scenario("00001-0001", LifecycleStatus.APPROVED)],
    )
    ctx = _ctx(tmp_path, mapping)

    class _Runner:
        async def run(self, context, targets, *, cursor=None):
            return [
                ScenarioOutcome(sub_bid="00001-0001", test_paths=["t1.py", "t2.py"])
            ]

    stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type, ty:invalid-argument-type]
    await stage.run(ctx)

    saved = MappingArtifact.load(tmp_path / "mapping.yaml")
    entry = saved.base_bids[0].scenarios[0]
    assert entry.lifecycle_status == LifecycleStatus.LIVE
    assert entry.tests == ["t1.py", "t2.py"]


@pytest.mark.asyncio
async def test_automation_stage_emits_scenario_live(tmp_path):
    mapping = _make_mapping(
        tmp_path,
        [_scenario("00001-0001", LifecycleStatus.APPROVED)],
    )
    ctx = _ctx(tmp_path, mapping)

    class _Runner:
        async def run(self, context, targets, *, cursor=None):
            return [ScenarioOutcome(sub_bid="00001-0001", test_paths=["t.py"])]

    stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type, ty:invalid-argument-type]
    await stage.run(ctx)

    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert types.count("scenario_live") == 1
    assert "stage_started" in types
    assert "stage_completed" in types


@pytest.mark.asyncio
async def test_automation_stage_invokes_p3_guard_for_each_target(tmp_path):
    """P3 enforcement is explicit at target-build time, not just implicit in the filter."""
    from unittest.mock import patch

    mapping = _make_mapping(
        tmp_path,
        [_scenario("00001-0001", LifecycleStatus.APPROVED)],
    )
    ctx = _ctx(tmp_path, mapping)

    class _Runner:
        async def run(self, context, targets, *, cursor=None):
            return [
                ScenarioOutcome(sub_bid=t.sub_bid, test_paths=["t.py"]) for t in targets
            ]

    with patch(
        "mage.orchestration.automation.guard_automation_entry", autospec=True
    ) as mock_guard:
        stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type, ty:invalid-argument-type]
        await stage.run(ctx)
        assert mock_guard.call_count == 1
