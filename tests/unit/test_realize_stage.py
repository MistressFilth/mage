"""Tests for RealizeStage.run_increment."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from mage.agents.realize import RealizeAgent, RealizeOutput
from mage.artifacts.inspect import InspectJournalEntry
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.realize import RealizeStage
from mage.orchestration.runner import Increment, ScenarioTarget


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


class _StubAgent:
    def __init__(self, output: RealizeOutput) -> None:
        self._output = output

    async def run(self, **kwargs) -> RealizeOutput:
        return self._output


class _RecordingRunner:
    def __init__(self, stdout: str = "diff --git a/foo.py\n+new line\n") -> None:
        self.stdout = stdout
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> CompletedProcess[str]:
        self.calls.append((list(command), Path(cwd)))
        return CompletedProcess(command, 0, stdout=self.stdout, stderr="")


@pytest.mark.asyncio
async def test_run_increment_returns_increment_result_with_diff(tmp_path):
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _StubAgent(RealizeOutput(files_changed=["foo.py", "bar.py"], summary="ok"))
    runner = _RecordingRunner(stdout="diff payload")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    result = await stage.run_increment(ctx, target=target, increment=increment)

    assert result.files_changed == ["foo.py", "bar.py"]
    assert result.summary == "ok"
    assert result.diff == "diff payload"
    assert len(runner.calls) == 1
    command, _cwd = runner.calls[0]
    assert command[:3] == ["git", "diff", "--unified=10"]
    assert command[-3:] == ["--", "foo.py", "bar.py"]


@pytest.mark.asyncio
async def test_run_increment_uses_default_runner_when_none_provided(
    tmp_path, monkeypatch
):
    """The default runner must exist and be callable; tests don't hit real git."""
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _StubAgent(RealizeOutput(files_changed=[], summary="nothing"))

    def fake_run(command, *, cwd):
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mage.orchestration.realize._default_command_runner", fake_run)
    stage = RealizeStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]

    result = await stage.run_increment(ctx, target=target, increment=increment)

    assert result.diff == ""


@pytest.mark.asyncio
async def test_run_increment_emits_realize_increment_done(tmp_path):
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _StubAgent(RealizeOutput(files_changed=["x.py"], summary=""))
    runner = _RecordingRunner(stdout="")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    await stage.run_increment(ctx, target=target, increment=increment)

    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert "realize_increment_done" in types


class _RecordingAgent(RealizeAgent):
    """Stub RealizeAgent that captures the kwargs passed to `run()`."""

    def __init__(self, output: RealizeOutput) -> None:
        from typing import Any

        self._output = output
        self.calls: list[dict] = []
        # skip parent __init__ (no Pydantic-AI Agent in tests)
        self._model: Any = None
        self._system_prompt_only = True

    async def run(self, **kwargs) -> RealizeOutput:
        self.calls.append(kwargs)
        return self._output


def _journal_entry(
    *, sub_bid: str, finding_id: str, route: str = "code", ts: datetime | None = None
) -> InspectJournalEntry:
    return InspectJournalEntry(
        timestamp=ts or datetime.now(UTC),
        iteration=1,
        dimension="increment_quality",
        severity="major",
        route=route,  # type: ignore[arg-type]
        finding_id=finding_id,
        location=f"{sub_bid}.py:1",
        issue="issue",
        rationale="rationale",
    )


@pytest.mark.asyncio
async def test_run_increment_pulls_carry_forward_from_inspect_journal(tmp_path):
    """Pins the R3 / R21 carry-forward contract: RealizeStage builds
    `carry_forward` from the last `per_scenario_window` entries of the
    target sub_bid's inspect_journal.
    """
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _RecordingAgent(RealizeOutput(files_changed=[], summary=""))
    runner = _RecordingRunner(stdout="")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    # Plant a single journal entry on the target sub_bid.
    entry = _journal_entry(sub_bid="00001-0001", finding_id="f-1")
    ctx.mapping = ctx.mapping.append_inspect_journal("00001-0001", entry)

    await stage.run_increment(ctx, target=target, increment=increment)

    assert len(agent.calls) == 1
    carry_forward = agent.calls[0]["carry_forward"]
    assert len(carry_forward) == 1
    assert carry_forward[0].finding_id == "f-1"
    assert carry_forward[0].route == "code"


@pytest.mark.asyncio
async def test_run_increment_pulls_cross_scenario_observations_from_siblings(tmp_path):
    """Pins the R3 / R21 cross-scenario contract: entries from sibling
    sub_bids appear in `cross_scenario_observations`, ordered most-recent
    first, truncated to `cross_scenario_window`.
    """
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _RecordingAgent(RealizeOutput(files_changed=[], summary=""))
    runner = _RecordingRunner(stdout="")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    # Plant entries on a sibling sub_bid; none on the target.
    base = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
    for i, fid in enumerate(["sib-1", "sib-2", "sib-3", "sib-4"]):
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "00001-0002",
            _journal_entry(
                sub_bid="00001-0002",
                finding_id=fid,
                ts=base.replace(minute=i),
            ),
        )

    await stage.run_increment(ctx, target=target, increment=increment)

    cross = agent.calls[0]["cross_scenario_observations"]
    # Default cross_scenario_window is 3, so only the most-recent 3 survive.
    assert len(cross) == 3
    assert [e.finding_id for e in cross] == ["sib-4", "sib-3", "sib-2"]


@pytest.mark.asyncio
async def test_run_increment_carry_forward_window_respects_size(tmp_path):
    """`per_scenario_window` truncates the per-scenario slice."""
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _RecordingAgent(RealizeOutput(files_changed=[], summary=""))
    runner = _RecordingRunner(stdout="")
    stage = RealizeStage(
        ctx.events_log,
        agent=agent,
        command_runner=runner,  # type: ignore[arg-type]
        per_scenario_window=2,
    )

    for fid in ["a", "b", "c"]:
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "00001-0001", _journal_entry(sub_bid="00001-0001", finding_id=fid)
        )

    await stage.run_increment(ctx, target=target, increment=increment)

    carry_forward = agent.calls[0]["carry_forward"]
    assert [e.finding_id for e in carry_forward] == ["b", "c"]
