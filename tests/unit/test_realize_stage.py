"""Tests for RealizeStage.run_increment."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.agents.realize import RealizeAgent, RealizeOutput
from mage.artifacts.inspect import InspectJournalEntry
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.realize import RealizeStage
from mage.orchestration.runner import Increment, ScenarioTarget
from mage.verification.host_overrides import HostConfig


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
    stage = RealizeStage(
        ctx.events_log,
        agent=agent,  # ty: ignore[invalid-argument-type]
        host_config=HostConfig(),
    )

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
        route=route,  # ty: ignore[invalid-argument-type]
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
    stage = RealizeStage(
        ctx.events_log,
        agent=agent,
        host_config=HostConfig(),
    )

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
    stage = RealizeStage(
        ctx.events_log,
        agent=agent,
        host_config=HostConfig(),
    )

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
    stage = RealizeStage(
        ctx.events_log,
        agent=agent,
        host_config=HostConfig(per_scenario_window=2),
    )

    for fid in ["a", "b", "c"]:
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "00001-0001", _journal_entry(sub_bid="00001-0001", finding_id=fid)
        )

    await stage.run_increment(ctx, target=target, increment=increment)

    carry_forward = agent.calls[0]["carry_forward"]
    assert [e.finding_id for e in carry_forward] == ["b", "c"]


def _git_init(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)


@pytest.mark.asyncio
async def test_run_increment_diff_emits_incomplete_event_on_path_traversal(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
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
    agent = _StubAgent(RealizeOutput(files_changed=["../escape.txt"], summary=""))
    stage = RealizeStage(
        ctx.events_log,
        agent,  # ty: ignore[invalid-argument-type]
        host_config=HostConfig(),
    )

    result = await stage.run_increment(ctx, target=target, increment=increment)

    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert "realize_increment_diff_incomplete" in types
    assert result.diff == ""


def test_increment_diff_excludes_prior_changes(tmp_path: Path) -> None:
    """The repro from P26 findings: prior-increment dirty change must NOT
    appear in the current increment's diff.

    Exercises `compute_unified_diff` directly with a pre-snapshot taken
    between increment 1's dirty write and increment 2's edits. The
    increment-relative diff must show only increment 2's additions; the
    increment 1 line is pre-existing context and must not be marked `-`.
    """
    import subprocess

    from mage.orchestration.increment_diff import compute_unified_diff, snapshot_tree

    _git_init(tmp_path)
    (tmp_path / "foo.py").write_text("v1\n")
    subprocess.run(["git", "add", "foo.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    # Seed a tracked-unstaged change from "increment 1"
    (tmp_path / "foo.py").write_text("v1\nINCREMENT1_DIRTY\n")

    pre = snapshot_tree(tmp_path)
    (tmp_path / "foo.py").write_text("v1\nINCREMENT1_DIRTY\nINCREMENT2_EDIT\n")
    (tmp_path / "bar.py").write_text("NEW FILE\n")
    diff, warnings = compute_unified_diff(tmp_path, ["foo.py", "bar.py"], pre)

    assert "INCREMENT2_EDIT" in diff
    assert "NEW FILE" in diff
    assert "+INCREMENT2_EDIT" in diff
    # The increment 1 dirty line must show only as context, not as a deletion.
    assert "-INCREMENT1_DIRTY" not in diff
    assert warnings == []
