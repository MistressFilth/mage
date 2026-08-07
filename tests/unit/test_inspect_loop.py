"""Tests for InspectLoopStage.inspect_increment."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.etch import ScenarioInspectHalted
from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.inspect_loop import InspectLoopStage
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import CheckResult


def _context(tmp_path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


class _Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    location: str
    issue: str
    suggestion: str
    severity: str
    route: Literal["spec", "code", "cosmetic"]


class _Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    findings: list[_Finding]


class _Reviewer:
    def __init__(self, verdict: _Verdict) -> None:
        self._verdict = verdict
        self.calls: list[dict] = []

    async def run(self, **kwargs) -> _Verdict:
        self.calls.append(kwargs)
        return self._verdict


class _Mechanical:
    def __init__(self, results: list[CheckResult]) -> None:
        self._results = results
        self.scopes: list[str] = []

    def verify(self, *, scope: str) -> list[CheckResult]:
        self.scopes.append(scope)
        return self._results


def _target() -> ScenarioTarget:
    return ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )


def _increment() -> Increment:
    return Increment(index=0, step="seed", red_test_path="t.py", red_test_code="...")


@pytest.mark.asyncio
async def test_clean_increment_returns_none(tmp_path):
    ctx = _context(tmp_path)
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = await stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route is None
    assert mech.scopes == ["increment"]
    events = ctx.events_log.read_all()
    assert any(e.event_type == EventType.INSPECT_LOOP_PASSED for e in events), (
        "INSPECT_LOOP_PASSED must be emitted on the clean-pass path"
    )


@pytest.mark.asyncio
async def test_code_route_re_loops(tmp_path):
    ctx = _context(tmp_path)
    finding = _Finding(
        id="f1",
        location="a.py:1",
        issue="naming",
        suggestion="rename",
        severity="major",
        route="code",
    )
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[finding]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = await stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route == "code"
    events = ctx.events_log.read_all()
    failed = [e for e in events if e.event_type == EventType.INSPECT_LOOP_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["reason"] == "code_route"
    assert failed[0].payload["code_finding_count"] == 1
    assert failed[0].payload["sub_bid"] == "00001-0001"


@pytest.mark.asyncio
async def test_cosmetic_route_returns_none_so_runner_does_not_re_loop(tmp_path):
    """Per GC-9: cosmetic is queued and does not re-loop. The runner must see
    None for cosmetic-only passes, not "cosmetic", so the while loop breaks."""
    ctx = _context(tmp_path)
    finding = _Finding(
        id="f1",
        location="a.py:1",
        issue="wording",
        suggestion="tweak",
        severity="minor",
        route="cosmetic",
    )
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[finding]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = await stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route is None
    cosmetic = ctx.mapping.cosmetic_findings
    assert len(cosmetic) == 1
    events = ctx.events_log.read_all()
    completed = [e for e in events if e.event_type == EventType.INSPECT_LOOP_COMPLETED]
    assert len(completed) == 1
    assert completed[0].payload["cosmetic_finding_count"] == 1
    assert completed[0].payload["sub_bid"] == "00001-0001"


@pytest.mark.asyncio
async def test_spec_route_returns_spec(tmp_path):
    ctx = _context(tmp_path)
    finding = _Finding(
        id="f1",
        location="a.py:1",
        issue="wrong contract",
        suggestion="rewrite spec",
        severity="critical",
        route="spec",
    )
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[finding]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = await stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route == "spec"
    events = ctx.events_log.read_all()
    failed = [e for e in events if e.event_type == EventType.INSPECT_LOOP_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["reason"] == "spec_route"
    assert failed[0].payload["sub_bid"] == "00001-0001"

    revision = [
        e for e in events if e.event_type == EventType.SCENARIO_REVISION_REQUESTED
    ]
    assert len(revision) == 1


@pytest.mark.asyncio
async def test_budget_exceeded_emits_failed_then_raises(tmp_path):
    """Per the per-loop budget guard: when iteration > per_loop_max_iterations,
    inspect_increment must emit INSPECT_LOOP_FAILED with reason='per_loop_budget_exceeded'
    BEFORE raising ScenarioInspectHalted."""
    ctx = _context(tmp_path)
    ctx.iteration = 3
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(
            test_runner_command=["pytest"], per_loop_max_iterations=2
        ),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    with pytest.raises(ScenarioInspectHalted):
        await stage.inspect_increment(
            ctx, target=_target(), increment=_increment(), result=result
        )

    events = ctx.events_log.read_all()
    failed = [e for e in events if e.event_type == EventType.INSPECT_LOOP_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["reason"] == "per_loop_budget_exceeded"
    assert failed[0].payload["sub_bid"] == "00001-0001"
    assert failed[0].payload["iteration"] == 3
