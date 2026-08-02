"""Verify RealizeStage honors HostConfig.{per_scenario_window,cross_scenario_window}.

Spec R3 / R21. Pins the flow-through contract end-to-end: the constructor
receives host_config; the helpers read from it; run_increment passes the
resulting slices to the agent.

The test stubs and helpers here mirror the ones in
``tests/unit/test_realize_stage.py`` — keep them in sync so future
refactors land in both files.
"""

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


class _RecordingAgent(RealizeAgent):
    """Stub RealizeAgent that captures the kwargs passed to `run()`.

    Mirrors the helper in test_realize_stage.py (line 128-142):
    RealizeAgent is a Pydantic-AI Agent, so the stub skips its parent's
    __init__ and sets the two attributes RealizeAgent.run() reads.
    """

    def __init__(self) -> None:
        from typing import Any

        self.calls: list[dict] = []
        # skip parent __init__ (no Pydantic-AI Agent in tests)
        self._model: Any = None
        self._system_prompt_only = True

    async def run(self, **kwargs) -> RealizeOutput:
        self.calls.append(kwargs)
        return RealizeOutput(files_changed=[], summary="")


def _journal_entry(
    *, sub_bid: str, finding_id: str, route: str = "code", ts: datetime | None = None
) -> InspectJournalEntry:
    """Mirror the helper in test_realize_stage.py (line 145-158) byte-for-byte."""
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


def _ctx(tmp_path: Path) -> tuple[PipelineContext, EventsLog]:
    log = EventsLog(tmp_path / "events.jsonl")
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=log,
        plan_path=tmp_path / "plan.md",
        iteration=1,
        host_config=HostConfig(per_scenario_window=2, cross_scenario_window=2),
    )
    return ctx, log


def _scenario_target(sub_bid: str = "00001-0001") -> ScenarioTarget:
    return ScenarioTarget(
        base_bid="00001",
        sub_bid=sub_bid,
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )


def _increment() -> Increment:
    return Increment(index=0, step="seed", red_test_path="t.py", red_test_code="...")


class TestHostConfigFlowThrough:
    @staticmethod
    def _stage(
        host_config: HostConfig, tmp_path: Path
    ) -> tuple[RealizeStage, _RecordingAgent]:
        log = EventsLog(tmp_path / "events.jsonl")
        agent = _RecordingAgent()
        stage = RealizeStage(log, agent=agent, host_config=host_config)  # type: ignore[arg-type]
        return stage, agent

    @pytest.mark.asyncio
    async def test_per_scenario_window_truncates(self, tmp_path: Path) -> None:
        host_config = HostConfig(per_scenario_window=2, cross_scenario_window=3)
        ctx, _ = _ctx(tmp_path)
        ctx.host_config = host_config
        stage, agent = self._stage(host_config, tmp_path)

        # Three same-sub_bid journal entries; window=2 keeps the last two.
        for fid in ["a", "b", "c"]:
            ctx.mapping = ctx.mapping.append_inspect_journal(
                "00001-0001",
                _journal_entry(
                    sub_bid="00001-0001",
                    finding_id=fid,
                    ts=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                ),
            )

        await stage.run_increment(
            ctx, target=_scenario_target(), increment=_increment()
        )

        carry_forward = agent.calls[0]["carry_forward"]
        assert [e.finding_id for e in carry_forward] == ["b", "c"]

    @pytest.mark.asyncio
    async def test_cross_scenario_window_truncates_and_sorts(
        self, tmp_path: Path
    ) -> None:
        host_config = HostConfig(per_scenario_window=5, cross_scenario_window=2)
        ctx, _ = _ctx(tmp_path)
        ctx.host_config = host_config
        stage, agent = self._stage(host_config, tmp_path)

        # Three siblings, one entry each, distinct minutes. Algorithm under test:
        # per-sibling slice -> entries[-2:] = [its_one_entry]; concat, sort
        # timestamp desc, trim to 2 -> top-2 by timestamp.
        base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "other-X",
            _journal_entry(
                sub_bid="other-X", finding_id="x", ts=base.replace(minute=10)
            ),
        )
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "other-Y",
            _journal_entry(
                sub_bid="other-Y", finding_id="y", ts=base.replace(minute=20)
            ),
        )
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "other-Z",
            _journal_entry(
                sub_bid="other-Z", finding_id="z", ts=base.replace(minute=15)
            ),
        )

        await stage.run_increment(
            ctx, target=_scenario_target(), increment=_increment()
        )

        cross = agent.calls[0]["cross_scenario_observations"]
        assert [e.finding_id for e in cross] == ["y", "z"]

    @pytest.mark.asyncio
    async def test_per_scenario_window_zero_yields_empty(self, tmp_path: Path) -> None:
        host_config = HostConfig(per_scenario_window=0, cross_scenario_window=3)
        ctx, _ = _ctx(tmp_path)
        ctx.host_config = host_config
        stage, agent = self._stage(host_config, tmp_path)

        # Three same-sub_bid journal entries; window=0 must clamp to empty
        # (not ``my_journal[-0:]`` which is ``my_journal[0:]`` = full list).
        for fid in ["a", "b", "c"]:
            ctx.mapping = ctx.mapping.append_inspect_journal(
                "00001-0001",
                _journal_entry(
                    sub_bid="00001-0001",
                    finding_id=fid,
                    ts=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                ),
            )

        await stage.run_increment(
            ctx, target=_scenario_target(), increment=_increment()
        )

        assert agent.calls[0]["carry_forward"] == []

    @pytest.mark.asyncio
    async def test_cross_scenario_window_zero_yields_empty(
        self, tmp_path: Path
    ) -> None:
        host_config = HostConfig(per_scenario_window=5, cross_scenario_window=0)
        ctx, _ = _ctx(tmp_path)
        ctx.host_config = host_config
        stage, agent = self._stage(host_config, tmp_path)

        base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "other-X",
            _journal_entry(
                sub_bid="other-X", finding_id="x", ts=base.replace(minute=10)
            ),
        )
        ctx.mapping = ctx.mapping.append_inspect_journal(
            "other-Y",
            _journal_entry(
                sub_bid="other-Y", finding_id="y", ts=base.replace(minute=20)
            ),
        )

        await stage.run_increment(
            ctx, target=_scenario_target(), increment=_increment()
        )

        assert agent.calls[0]["cross_scenario_observations"] == []

    @pytest.mark.asyncio
    async def test_run_increment_passes_slices_to_agent(self, tmp_path: Path) -> None:
        host_config = HostConfig(per_scenario_window=3, cross_scenario_window=3)
        ctx, _ = _ctx(tmp_path)
        ctx.host_config = host_config
        stage, agent = self._stage(host_config, tmp_path)

        # No other-sub_bid entries: cross_scenario_observations must be [].
        # Two same-sub_bid entries: per_scenario_window=3 keeps both.
        for fid in ["a", "b"]:
            ctx.mapping = ctx.mapping.append_inspect_journal(
                "00001-0001",
                _journal_entry(sub_bid="00001-0001", finding_id=fid),
            )

        await stage.run_increment(
            ctx, target=_scenario_target(), increment=_increment()
        )

        assert agent.calls, "agent.run was not invoked"
        call = agent.calls[0]
        assert call["scenario_context"] == {"sub_bid": "00001-0001"}
        assert [e.finding_id for e in call["carry_forward"]] == ["a", "b"]
        assert call["cross_scenario_observations"] == []
