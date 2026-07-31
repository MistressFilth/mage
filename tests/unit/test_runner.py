"""Tests for FeatureRunner."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from mage.orchestration.runner import (
    AutomationCursor,
    FeatureRunner,
    Increment,
    IncrementResult,
    ScenarioOutcome,
    ScenarioTarget,
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
    def __init__(self, verdicts: list[_Verdict]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0

    async def run(self, **kwargs) -> _Verdict:
        self.calls += 1
        return (
            self._verdicts.pop(0)
            if self._verdicts
            else _Verdict(dimension="increment_quality", findings=[])
        )


class _Mechanical:
    def verify(self, *, scope: str):
        return []


def _target(sub_bid: str = "00001-0001") -> ScenarioTarget:
    return ScenarioTarget(
        base_bid="00001",
        sub_bid=sub_bid,
        scenario_name="happy",
        gherkin_body="",
        steps=["s1"],
    )


def _ctx(tmp_path):
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext

    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=None,  # type: ignore[arg-type]
        iteration=0,
    )


@pytest.mark.asyncio
async def test_clean_increment_produces_one_scenario_outcome(tmp_path):
    target = _target()

    class _Etch:
        async def run_scenario(self, ctx, t):
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")
            ]

    class _Realize:
        async def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class _Inspect:
        async def inspect_increment(self, ctx, *, target, increment, result):
            return None

    etch = _Etch()
    realize = _Realize()
    inspect = _Inspect()
    runner = FeatureRunner(
        etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8
    )  # type: ignore[arg-type]

    outcomes = await runner.run(_ctx(tmp_path), [target])

    assert outcomes == [ScenarioOutcome(sub_bid="00001-0001", test_paths=["t.py"])]
    assert runner.cursor is None  # cleared after a clean scenario


@pytest.mark.asyncio
async def test_code_route_re_loops_until_clean(tmp_path):
    target = _target()

    class _Etch:
        async def run_scenario(self, ctx, t):
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")
            ]

    etch = _Etch()

    verdicts = [
        _Verdict(
            dimension="iq",
            findings=[
                _Finding(
                    id="f",
                    location="a",
                    issue="x",
                    suggestion="y",
                    severity="major",
                    route="code",
                )
            ],
        ),
        _Verdict(dimension="iq", findings=[]),
    ]

    class _Realize:
        async def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    realize = _Realize()
    reviewer = _Reviewer(verdicts)

    class _Inspect:
        async def inspect_increment(self, ctx, *, target, increment, result):
            v = await reviewer.run()
            return "code" if v.findings else None

    inspect = _Inspect()
    runner = FeatureRunner(
        etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8
    )  # type: ignore[arg-type]

    outcomes = await runner.run(_ctx(tmp_path), [target])

    assert len(outcomes) == 1
    assert reviewer.calls == 2  # two inspect calls before clean


@pytest.mark.asyncio
async def test_spec_route_raises_scenario_inspect_halted(tmp_path):
    from mage.orchestration.etch import ScenarioInspectHalted

    target = _target()

    class _Etch:
        async def run_scenario(self, ctx, t):
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")
            ]

    class _Realize:
        async def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class _Inspect:
        async def inspect_increment(self, ctx, *, target, increment, result):
            return "spec"

    etch = _Etch()
    realize = _Realize()
    inspect = _Inspect()
    runner = FeatureRunner(
        etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8
    )  # type: ignore[arg-type]

    with pytest.raises(ScenarioInspectHalted):
        await runner.run(_ctx(tmp_path), [target])


@pytest.mark.asyncio
async def test_cosmetic_only_does_not_re_loop(tmp_path):
    target = _target()

    class _Etch:
        async def run_scenario(self, ctx, t):
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")
            ]

    class _Realize:
        async def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    calls = {"n": 0}

    class _Inspect:
        async def inspect_increment(self, ctx, **kwargs):
            calls["n"] += 1

    etch = _Etch()
    realize = _Realize()
    inspect = _Inspect()
    runner = FeatureRunner(
        etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8
    )  # type: ignore[arg-type]

    await runner.run(_ctx(tmp_path), [target])

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_resume_skips_completed_scenarios(tmp_path):
    """First scenario is already done; resume at the second."""
    t1 = _target(sub_bid="00001-0001")
    t2 = _target(sub_bid="00001-0002")

    etch_calls: list[str] = []

    class E:
        async def run_scenario(self, ctx, t):
            etch_calls.append(t.sub_bid)
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")
            ]

    class R:
        async def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class I:
        async def inspect_increment(self, ctx, *, target, increment, result):
            return None

    runner = FeatureRunner(
        etch=E(), realize=R(), inspect_loop=I(), per_loop_max_iterations=8
    )  # type: ignore[arg-type]
    cursor = AutomationCursor(sub_bid="00001-0002", increment_index=0, iteration=1)

    outcomes = await runner.run(_ctx(tmp_path), [t1, t2], cursor=cursor)

    assert etch_calls == ["00001-0002"]
    assert outcomes == [ScenarioOutcome(sub_bid="00001-0002", test_paths=["t.py"])]


@pytest.mark.asyncio
async def test_resume_at_mid_scenario_starts_at_cursor_iteration(tmp_path):
    """The cursor's iteration is the next attempt, not the completed one."""
    t1 = _target(sub_bid="00001-0001")
    inspect_iterations: list[int] = []

    class E:
        async def run_scenario(self, ctx, t):
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code=""),
                Increment(index=1, step="s2", red_test_path="t.py", red_test_code=""),
            ]

    class R:
        async def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class I:
        async def inspect_increment(self, ctx, *, target, increment, result):
            inspect_iterations.append(ctx.iteration)

    runner = FeatureRunner(
        etch=E(), realize=R(), inspect_loop=I(), per_loop_max_iterations=8
    )  # type: ignore[arg-type]
    cursor = AutomationCursor(sub_bid="00001-0001", increment_index=1, iteration=3)

    await runner.run(_ctx(tmp_path), [t1], cursor=cursor)

    # increment 0 was skipped (completed before halt); increment 1 starts at iter 3
    assert [i for i in inspect_iterations] == [3]


@pytest.mark.asyncio
async def test_cursor_cleared_after_clean_scenario(tmp_path):
    t1 = _target()

    class _Etch:
        async def run_scenario(self, c, t):
            return [
                Increment(index=0, step="s", red_test_path="t.py", red_test_code="")
            ]

    class _Realize:
        async def run_increment(self, c, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class _Inspect:
        async def inspect_increment(self, c, *, target, increment, result):
            return None

    runner = FeatureRunner(
        etch=_Etch(),
        realize=_Realize(),
        inspect_loop=_Inspect(),
        per_loop_max_iterations=8,
    )
    await runner.run(
        _ctx(tmp_path),
        [t1],
        cursor=AutomationCursor(sub_bid="00001-0001", increment_index=0, iteration=1),
    )
    assert runner.cursor is None
