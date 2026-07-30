"""End-to-end: 1 feature x 2 scenarios -> live -> Inspect-feature passes -> Settle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


class TestE2EInspectSettle:
    @pytest.mark.asyncio
    async def test_full_feature_through_settle(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        def make_reviewer(dim):
            class R:
                dimension = dim

                async def run(self, **kwargs):
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[],
                    )

            return R()

        reviewers = [
            make_reviewer(d)
            for d in [
                "spec_compliance",
                "scenario_clarity",
                "step_grammar",
                "testability",
                "determinism",
                "naming_idiom",
                "lifecycle_tags",
                "cross_scenario",
            ]
        ]

        # Run InspectFeature
        from mage.verification.mechanical import MechanicalVerifier

        inspect_stage = InspectFeatureStage(
            log,
            reviewers=reviewers,
            mechanical_verifier=MechanicalVerifier(checks=[]),
            host_config=HostConfig(),
        )
        artifact = await inspect_stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[
                {"sub_bid": "00000-0", "scenario_name": "happy"},
                {"sub_bid": "00000-1", "scenario_name": "edge"},
            ],
        )
        assert artifact.ready_to_merge is True

        # Run SettleFeature with deterministic host-command responses.
        from subprocess import CompletedProcess

        def command_runner(command, *, cwd):
            outputs = {
                ("git", "rev-parse", "--git-dir"): str(tmp_path / ".git"),
                ("git", "rev-parse", "--git-common-dir"): str(tmp_path / ".git"),
                ("git", "rev-parse", "--show-toplevel"): str(tmp_path),
                ("git", "branch", "--show-current"): "feature/inspect-settle",
            }
            return CompletedProcess(
                command,
                0,
                stdout=outputs.get(tuple(command), "") + "\n",
                stderr="",
            )

        settle_stage = SettleFeatureStage(log, command_runner=command_runner)
        await settle_stage.run_settle(ctx, feature_id="feat-1", disposition="kept")

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_passed" in types
        assert "settle_feature_finalized" in types
        assert "settle_cosmetic_queued" in types

        # Verify report file
        report = (tmp_path / ".haileris" / "settle" / "feat-1.md").read_text()
        assert "feat-1" in report
        assert "kept" in report


class TestE2EInspectFeatureHalt:
    @pytest.mark.asyncio
    async def test_eof_budget_overflow_raises_halt(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerFinding, ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import (
            InspectFeatureHalted,
            InspectFeatureStage,
        )
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=3,  # at eof_max_iterations
        )

        def make_reviewer(dim, severity="pass"):
            class R:
                dimension = dim

                async def run(self, **kwargs):
                    if severity == "pass":
                        return ReviewerVerdict(
                            dimension=dim,
                            outcome="pass",
                            draft_hash="",
                            reviewed_at=datetime.now(UTC),
                            reviewer_id=f"{dim}@v1",
                            findings=[],
                        )
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="fail",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[
                            ReviewerFinding(
                                id="f-1",
                                severity="critical",
                                location="00000-0",
                                issue="Critical",
                                rationale="Spec violation",
                                suggestion="Fix",
                                citations=["00000-0"],
                            )
                        ],
                    )

            return R()

        reviewers = [
            make_reviewer("spec_compliance", "critical"),
            *[
                make_reviewer(d)
                for d in [
                    "scenario_clarity",
                    "step_grammar",
                    "testability",
                    "determinism",
                    "naming_idiom",
                    "lifecycle_tags",
                    "cross_scenario",
                ]
            ],
        ]

        from mage.verification.mechanical import MechanicalVerifier

        stage = InspectFeatureStage(
            log,
            reviewers=reviewers,
            mechanical_verifier=MechanicalVerifier(checks=[]),
            host_config=HostConfig(eof_max_iterations=3),
        )

        with pytest.raises(InspectFeatureHalted):
            await stage.run_pass(
                ctx,
                feature_id="feat-1",
                scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
            )

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_halt_persisted" in types


class TestE2ECosmeticQueueAccumulation:
    @pytest.mark.asyncio
    async def test_minor_findings_flow_to_cosmetic_queue(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerFinding, ReviewerVerdict
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        def make_reviewer(dim, *, severity="pass"):
            findings = []
            if severity == "minor":
                findings = [
                    ReviewerFinding(
                        id="m-1",
                        severity="minor",
                        location="00000-0",
                        issue="Rephrase for clarity",
                        rationale="Cosmetic",
                        suggestion="Rephrase",
                        citations=["00000-0"],
                    )
                ]

            class R:
                dimension = dim

                async def run(self, **kwargs):
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass" if severity == "pass" else "fail",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=findings,
                    )

            return R()

        reviewers = [
            make_reviewer("spec_compliance"),
            make_reviewer("scenario_clarity", severity="minor"),
            *[
                make_reviewer(d)
                for d in [
                    "step_grammar",
                    "testability",
                    "determinism",
                    "naming_idiom",
                    "lifecycle_tags",
                    "cross_scenario",
                ]
            ],
        ]

        from mage.verification.mechanical import MechanicalVerifier

        stage = InspectFeatureStage(
            log,
            reviewers=reviewers,
            mechanical_verifier=MechanicalVerifier(checks=[]),
            host_config=HostConfig(),
        )
        artifact = await stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
        )

        assert artifact.ready_to_merge is True
        assert len(artifact.minor) == 1
