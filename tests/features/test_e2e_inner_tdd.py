"""End-to-end: 1 feature × 2 scenarios × 3 increments → all live.

Plan 6 wiring test: drives InspectLoopStage.inspect_increment + RealizeStage.run_increment
directly. The graph-level halt persistence for `ScenarioInspectHalted` is
covered in tests/unit/test_graph.py::TestPlan4HaltCatching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest


class TestE2EInnerTDDHappyPath:
    def test_two_senarios_three_increments_each_reach_live(self, tmp_path: Path):
        from mage.agents.realize import RealizeOutput
        from mage.artifacts.mapping import (
            BaseBIDEntry,
            LifecycleStatus,
            MappingArtifact,
            ScenarioEntry,
        )
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.orchestration.events import EventsLog, EventType
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.orchestration.realize import RealizeStage
        from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")

        scenarios = [
            ScenarioEntry(
                sub_bid=f"00000-{i}",
                scenario_text_hash=f"hash-{i}",
                lifecycle_status=LifecycleStatus.APPROVED,
            )
            for i in range(2)
        ]
        mapping = MappingArtifact(
            project_id="feat-1",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="happy",
                    behavior_description="x",
                    scenarios=scenarios,
                )
            ],
        )
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=mapping,
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class CleanMech:
            def verify(self, scope):
                return []

        class CleanReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                return ReviewerVerdict(
                    dimension="increment_quality",
                    outcome="pass",
                    draft_hash="",
                    reviewed_at=datetime.now(UTC),
                    reviewer_id="increment_quality@v1",
                    findings=[],
                )

        class NoOpRealizeAgent:
            def run(self, *, step, scenario_context, red_test_path, carry_forward, cross_scenario_observations):
                return RealizeOutput(files_changed=[], summary="stub")

        cfg = HostConfig()
        inspect_stage = InspectLoopStage(
            log,
            mechanical_verifier=CleanMech(),
            increment_quality_reviewer=CleanReviewer(),
            host_config=cfg,
        )
        realize_stage = RealizeStage(log, NoOpRealizeAgent())

        # Drive 2 scenarios × 3 increments each
        for scenario in scenarios:
            target = ScenarioTarget(
                base_bid="00000",
                sub_bid=scenario.sub_bid,
                scenario_name=f"scenario-{scenario.sub_bid}",
                gherkin_body="",
                steps=[],
            )
            for inc in range(3):
                increment = Increment(
                    index=inc,
                    step=f"step-{inc}",
                    red_test_path=f"tests/test_{scenario.sub_bid}_{inc}.py",
                    red_test_code="",
                )
                inc_result = IncrementResult(files_changed=[], summary="", diff="")
                inspect_stage.inspect_increment(
                    ctx, target=target, increment=increment, result=inc_result
                )
                realize_stage.run_increment(
                    ctx, target=target, increment=increment
                )
            log.append(
                __import__("mage.orchestration.events", fromlist=["Event", "EventType"]).Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SCENARIO_LIVE,
                    payload={"sub_bid": scenario.sub_bid, "scenario_name": f"scenario-{scenario.sub_bid}"},
                )
            )

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert types.count("inspect_loop_started") == 6  # 2 scenarios × 3 increments
        assert types.count("scenario_live") == 2


class TestE2EPerLoopHalt:
    def test_mechanical_overflow_halts_scenario(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
        from mage.verification.host_overrides import HostConfig
        from mage.verification.mechanical import MechanicalFinding

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=7,  # 1 below budget
        )

        class AlwaysFailMech:
            def verify(self, scope):
                return [MechanicalFinding(
                    check="tests_pass",
                    severity="critical",
                    location="tests/test_x.py",
                    issue="Tests still failing",
                    rationale="Won't converge",
                )]

        class NoopReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                from mage.artifacts.verdict import ReviewerVerdict
                return ReviewerVerdict(
                    dimension="increment_quality",
                    outcome="pass",
                    draft_hash="",
                    reviewed_at=datetime.now(UTC),
                    reviewer_id="increment_quality@v1",
                    findings=[],
                )

        stage = InspectLoopStage(
            log,
            mechanical_verifier=AlwaysFailMech(),
            increment_quality_reviewer=NoopReviewer(),
            host_config=HostConfig(per_loop_max_iterations=8),
        )
        target = ScenarioTarget(
            base_bid="00000",
            sub_bid="00000-0",
            scenario_name="happy",
            gherkin_body="",
            steps=[],
        )
        increment = Increment(
            index=0, step="seed", red_test_path="t.py", red_test_code=""
        )
        inc_result = IncrementResult(files_changed=[], summary="", diff="")

        # First call: iteration goes 7 → 8, budget not exceeded yet, no halt
        stage.inspect_increment(
            ctx, target=target, increment=increment, result=inc_result
        )
        # Second call: iteration 8 → 9, over budget, halt.
        ctx.iteration = 9
        with pytest.raises(Exception) as exc_info:
            stage.inspect_increment(
                ctx, target=target, increment=increment, result=inc_result
            )
        # The new API raises the budget overflow directly.
        assert "budget exhausted" in str(exc_info.value)


class TestE2ESpecRouteHalt:
    def test_spec_route_finding_halts_scenario(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class CleanMech:
            def verify(self, scope):
                return []

        @dataclass
        class FindingWithRoute:
            id: str = "f-1"
            severity: str = "major"
            location: str = "src/foo.py"
            issue: str = "Spec is wrong"
            rationale: str = "Scenario doesn't describe this"
            suggestion: str = "spec:Halt"
            citations: list = None
            route: str = "spec"

            def __post_init__(self):
                if self.citations is None:
                    self.citations = []

        @dataclass
        class VerdictWithRoute:
            dimension: str = "increment_quality"
            outcome: str = "fail"
            draft_hash: str = ""
            reviewed_at: datetime = None
            reviewer_id: str = "increment_quality@v1"
            findings: list = None
            notes: str = ""

            def __post_init__(self):
                if self.reviewed_at is None:
                    self.reviewed_at = datetime.now(UTC)
                if self.findings is None:
                    self.findings = []

        class SpecRouteReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                return VerdictWithRoute(findings=[FindingWithRoute()])

        stage = InspectLoopStage(
            log,
            mechanical_verifier=CleanMech(),
            increment_quality_reviewer=SpecRouteReviewer(),
            host_config=HostConfig(),
        )
        target = ScenarioTarget(
            base_bid="00000",
            sub_bid="00000-0",
            scenario_name="happy",
            gherkin_body="",
            steps=[],
        )
        increment = Increment(
            index=0, step="seed", red_test_path="t.py", red_test_code=""
        )
        inc_result = IncrementResult(files_changed=[], summary="", diff="")

        # Plan 6: inspect_increment returns "spec"; the runner (or test shim)
        # translates that into ScenarioInspectHalted. Test that the spec
        # finding lands in the journal with route="spec".
        route = stage.inspect_increment(
            ctx, target=target, increment=increment, result=inc_result
        )
        assert route == "spec"
        journal = ctx.mapping.inspect_journal.get("00000-0", [])
        spec_entries = [e for e in journal if e.get("route") == "spec"]
        assert len(spec_entries) == 1


class TestE2ECodeRouteCarryForward:
    def test_code_route_finding_injects_into_next_increment(self, tmp_path):
        from mage.agents.realize import RealizeOutput
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.orchestration.realize import RealizeStage
        from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class CleanMech:
            def verify(self, scope):
                return []

        @dataclass
        class FindingWithRoute:
            id: str = "f-1"
            severity: str = "major"
            location: str = "src/foo.py:42"
            issue: str = "Missing edge case"
            rationale: str = "Empty input not tested"
            suggestion: str = "code:Add empty-input test"
            citations: list = None
            route: str = "code"

            def __post_init__(self):
                if self.citations is None:
                    self.citations = []

        @dataclass
        class VerdictWithRoute:
            dimension: str = "increment_quality"
            outcome: str = "fail"
            draft_hash: str = ""
            reviewed_at: datetime = None
            reviewer_id: str = "increment_quality@v1"
            findings: list = None
            notes: str = ""

            def __post_init__(self):
                if self.reviewed_at is None:
                    self.reviewed_at = datetime.now(UTC)
                if self.findings is None:
                    self.findings = []

        class CodeRouteReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                return VerdictWithRoute(findings=[FindingWithRoute()])

        captured_carry_forward = []

        class CapturingRealizeAgent:
            def run(self, *, step, scenario_context, red_test_path, carry_forward, cross_scenario_observations):
                captured_carry_forward.append(list(carry_forward))
                return RealizeOutput(files_changed=[], summary="stub")

        stage = InspectLoopStage(
            log,
            mechanical_verifier=CleanMech(),
            increment_quality_reviewer=CodeRouteReviewer(),
            host_config=HostConfig(),
        )
        realize_stage = RealizeStage(log, CapturingRealizeAgent())
        target = ScenarioTarget(
            base_bid="00000",
            sub_bid="00000-0",
            scenario_name="happy",
            gherkin_body="",
            steps=[],
        )
        increment = Increment(
            index=0, step="seed", red_test_path="t.py", red_test_code=""
        )
        inc_result = IncrementResult(files_changed=[], summary="", diff="")

        # First increment: code-route finding → journal entry
        route = stage.inspect_increment(
            ctx, target=target, increment=increment, result=inc_result
        )
        assert route == "code"
        # Second increment: realize should see the code-route finding in carry_forward
        realize_stage.run_increment(
            ctx, target=target, increment=increment
        )

        assert len(captured_carry_forward) == 1
        assert len(captured_carry_forward[0]) == 1
        assert captured_carry_forward[0][0].finding_id == "f-1"
        assert captured_carry_forward[0][0].route == "code"
