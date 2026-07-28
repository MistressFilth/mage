"""Tests for InspectLoopStage (mechanical + IncrementQualityReviewer + R20 routing)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest


class TestInspectLoopStage:
    def test_passes_when_mechanical_and_quality_clean(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class AlwaysPassMech:
            def run(self, scope):
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

        stage = InspectLoopStage(
            log,
            mechanical_verifier=AlwaysPassMech(),
            increment_quality_reviewer=CleanReviewer(),
            host_config=HostConfig(),
        )
        stage._run_single_increment(
            ctx,
            sub_bid="00000-0",
            increment_diff="",
            new_test="",
            scenario_steps=[],
        )

        types = [e.event_type.value for e in log.read_all()]
        assert "inspect_loop_started" in types
        assert "inspect_loop_passed" in types
        assert "inspect_loop_completed" in types

    def test_halts_on_spec_route_finding(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class AlwaysPassMech:
            def run(self, scope):
                return []

        @dataclass
        class FindingWithRoute:
            id: str
            severity: str
            location: str
            issue: str
            rationale: str
            suggestion: str
            citations: list
            route: str = "spec"

        @dataclass
        class VerdictWithRoute:
            dimension: str = "increment_quality"
            outcome: str = "fail"
            draft_hash: str = ""
            reviewed_at: datetime | None = None
            reviewer_id: str = "increment_quality@v1"
            findings: list | None = None
            notes: str = ""

            def __post_init__(self):
                if self.reviewed_at is None:
                    self.reviewed_at = datetime.now(UTC)
                if self.findings is None:
                    self.findings = []

        class SpecRouteReviewerWithRoute:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                return VerdictWithRoute(
                    findings=[
                        FindingWithRoute(
                            id="f-1",
                            severity="major",
                            location="src/foo.py",
                            issue="Spec is wrong",
                            rationale="Scenario doesn't describe this",
                            suggestion="Halt",
                            citations=[],
                            route="spec",
                        )
                    ]
                )

        stage = InspectLoopStage(
            log,
            mechanical_verifier=AlwaysPassMech(),
            increment_quality_reviewer=SpecRouteReviewerWithRoute(),
            host_config=HostConfig(),
        )

        with pytest.raises(ScenarioInspectHalted):
            stage._run_single_increment(
                ctx,
                sub_bid="00000-0",
                increment_diff="",
                new_test="",
                scenario_steps=[],
            )

    def test_halts_on_mechanical_overflow(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.etch import ScenarioInspectHalted
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=8,
        )

        class AlwaysFailMech:
            def run(self, scope):
                from mage.verification.mechanical import MechanicalFinding

                return [
                    MechanicalFinding(
                        check="tests_pass",
                        severity="critical",
                        location="tests/test_x.py",
                        issue="Tests still failing",
                        rationale="Will not converge",
                    )
                ]

        class NoopReviewer:
            def run(self, *, increment_diff, new_test, scenario_steps, recent_journal_window):
                raise AssertionError("reviewer must not run after mechanical failure")

        stage = InspectLoopStage(
            log,
            mechanical_verifier=AlwaysFailMech(),
            increment_quality_reviewer=NoopReviewer(),
            host_config=HostConfig(per_loop_max_iterations=8),
        )

        with pytest.raises(ScenarioInspectHalted):
            stage._run_single_increment(
                ctx,
                sub_bid="00000-0",
                increment_diff="",
                new_test="",
                scenario_steps=[],
            )
