"""Tests for RealizeStage.run_increment."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from mage.agents.realize import RealizeOutput
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

    def run(self, **kwargs) -> RealizeOutput:
        return self._output


class _RecordingRunner:
    def __init__(self, stdout: str = "diff --git a/foo.py\n+new line\n") -> None:
        self.stdout = stdout
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> CompletedProcess[str]:
        self.calls.append((list(command), Path(cwd)))
        return CompletedProcess(command, 0, stdout=self.stdout, stderr="")


def test_run_increment_returns_increment_result_with_diff(tmp_path):
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
    agent = _StubAgent(
        RealizeOutput(files_changed=["foo.py", "bar.py"], summary="ok")
    )
    runner = _RecordingRunner(stdout="diff payload")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    result = stage.run_increment(ctx, target=target, increment=increment)

    assert result.files_changed == ["foo.py", "bar.py"]
    assert result.summary == "ok"
    assert result.diff == "diff payload"
    assert len(runner.calls) == 1
    command, _cwd = runner.calls[0]
    assert command[:3] == ["git", "diff", "--unified=10"]
    assert command[-3:] == ["--", "foo.py", "bar.py"]


def test_run_increment_uses_default_runner_when_none_provided(tmp_path, monkeypatch):
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

    monkeypatch.setattr(
        "mage.orchestration.realize._default_command_runner", fake_run
    )
    stage = RealizeStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]

    result = stage.run_increment(ctx, target=target, increment=increment)

    assert result.diff == ""


def test_run_increment_emits_realize_increment_done(tmp_path):
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

    stage.run_increment(ctx, target=target, increment=increment)

    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert "realize_increment_done" in types
