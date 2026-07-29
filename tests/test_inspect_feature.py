"""Tests for InspectFeatureStage (eof full sweep + 3-tier routing)."""

from __future__ import annotations

from datetime import UTC, datetime


class TestInspectFeatureStage:
    def test_passes_when_all_reviewers_clean(self, tmp_path):
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
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

        # Build 8 reviewers, all pass. The plan-3 reviewers normally take
        # (draft, spec_context, mapping, events_log, verdict_path) and the
        # CrossScenarioReviewer takes (feature_summary, scenarios, mapping);
        # tests use anonymous stubs with a uniform signature so the dispatch
        # loop doesn't have to know about both shapes.
        def make_reviewer(dim):
            class CleanReviewer:
                dimension = dim

                def run(self, **kwargs):  # noqa: ARG002
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[],
                    )

            return CleanReviewer()

        reviewers = [
            make_reviewer("spec_compliance"),
            make_reviewer("scenario_clarity"),
            make_reviewer("step_grammar"),
            make_reviewer("testability"),
            make_reviewer("determinism"),
            make_reviewer("naming_idiom"),
            make_reviewer("lifecycle_tags"),
            make_reviewer("cross_scenario"),
        ]

        stage = InspectFeatureStage(
            log,
            reviewers=reviewers,
            host_config=HostConfig(),
        )

        artifact_content = stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
        )

        assert artifact_content.ready_to_merge is True
        assert artifact_content.iteration == 1
        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_started" in types
        assert "inspect_feature_finalized" in types
        assert "inspect_feature_passed" in types

    def test_critical_finding_marked_not_ready(self, tmp_path):
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

        def make_reviewer(dim, *, has_critical=False):
            class R:
                dimension = dim

                def run(self, **kwargs):  # noqa: ARG002
                    if has_critical:
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
                                    issue="Critical issue",
                                    rationale="Breaks the spec",
                                    suggestion="Fix",
                                    citations=["00000-0"],
                                )
                            ],
                        )
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
            make_reviewer("spec_compliance", has_critical=True),
            make_reviewer("scenario_clarity"),
            make_reviewer("step_grammar"),
            make_reviewer("testability"),
            make_reviewer("determinism"),
            make_reviewer("naming_idiom"),
            make_reviewer("lifecycle_tags"),
            make_reviewer("cross_scenario"),
        ]

        stage = InspectFeatureStage(
            log, reviewers=reviewers, host_config=HostConfig()
        )
        artifact = stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
        )

        assert artifact.ready_to_merge is False
        assert len(artifact.critical) == 1
