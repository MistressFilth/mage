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

    def test_mechanical_finding_persisted_to_inspect_journal(self, tmp_path):
        """Regression: mechanical-fail that doesn't halt must still leave an
        entry in mapping.inspect_journal[sub_bid] (Finding 2 from review).
        Without this, the next Realize prompt's recent_journal_window would
        miss the mechanical feedback.
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig
        from mage.verification.mechanical import MechanicalFinding

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class AlwaysFailMech:
            def run(self, scope):
                return [
                    MechanicalFinding(
                        check="tests_pass",
                        severity="critical",
                        location="tests/test_x.py",
                        issue="Tests still failing",
                        rationale="Will not converge",
                    )
                ]

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

        # Budget high enough that the mechanical-fail returns to Realize
        # without halting (the halt scenario is covered separately).
        stage = InspectLoopStage(
            log,
            mechanical_verifier=AlwaysFailMech(),
            increment_quality_reviewer=CleanReviewer(),
            host_config=HostConfig(per_loop_max_iterations=8),
        )

        stage._run_single_increment(
            ctx,
            sub_bid="00000-0",
            increment_diff="",
            new_test="",
            scenario_steps=[],
        )

        # The journal entry must be present even though we returned instead
        # of halting.
        sub_bid = "00000-0"
        assert sub_bid in ctx.mapping.inspect_journal, (
            f"expected mechanical finding persisted to inspect_journal[{sub_bid!r}], "
            f"got keys: {list(ctx.mapping.inspect_journal.keys())}"
        )
        entries = ctx.mapping.inspect_journal[sub_bid]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["dimension"] == "mechanical"
        assert entry["severity"] == "critical"
        assert entry["route"] == "code"
        assert entry["finding_id"] == "tests_pass"
        assert entry["location"] == "tests/test_x.py"
        assert entry["issue"] == "Tests still failing"
        assert entry["rationale"] == "Will not converge"
        assert entry["iteration"] == 1  # iteration was bumped from 0

    def test_mechanical_check_result_list_is_adapted(self, tmp_path):
        """Regression: Plan 1's MechanicalVerifier returns list[CheckResult],
        not list[MechanicalFinding]. The adapter must translate so the
        inspect journal entry has the expected fields (Finding 1 from review).
        """
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig
        from mage.verification.mechanical import CheckResult

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        class PlanOneStyleMech:
            """Returns list[CheckResult] (the real Plan 1 shape)."""

            def run(self, scope):
                return [
                    CheckResult(name="gherkin-syntax", outcome="fail", detail="missing Then"),
                    CheckResult(name="happy-path", outcome="pass", detail=None),
                ]

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
            mechanical_verifier=PlanOneStyleMech(),
            increment_quality_reviewer=CleanReviewer(),
            host_config=HostConfig(per_loop_max_iterations=8),
        )

        stage._run_single_increment(
            ctx,
            sub_bid="00000-0",
            increment_diff="",
            new_test="",
            scenario_steps=[],
        )

        # Adapter rules:
        # - CheckResult with outcome == "fail" → MechanicalFinding
        #   (severity="critical", check=name, issue=detail, rationale=detail)
        # - CheckResult with outcome == "pass" → dropped
        sub_bid = "00000-0"
        entries = ctx.mapping.inspect_journal[sub_bid]
        assert len(entries) == 1, f"expected 1 entry (pass dropped), got {entries}"
        entry = entries[0]
        assert entry["finding_id"] == "gherkin-syntax"
        assert entry["severity"] == "critical"
        assert entry["dimension"] == "mechanical"
        assert entry["issue"] == "missing Then"
        assert entry["rationale"] == "missing Then"
