"""End-to-end: 1 feature x 2 scenarios -> live -> Inspect-feature passes -> Settle."""

from __future__ import annotations

from datetime import UTC, datetime


class TestE2EInspectSettle:
    def test_full_feature_through_settle(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
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

                def run(self, **kwargs):  # noqa: ARG002
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
            make_reviewer(d) for d in [
                "spec_compliance", "scenario_clarity", "step_grammar", "testability",
                "determinism", "naming_idiom", "lifecycle_tags", "cross_scenario",
            ]
        ]

        # Run InspectFeature
        inspect_stage = InspectFeatureStage(log, reviewers=reviewers, host_config=HostConfig())
        artifact = inspect_stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[
                {"sub_bid": "00000-0", "scenario_name": "happy"},
                {"sub_bid": "00000-1", "scenario_name": "edge"},
            ],
        )
        assert artifact.ready_to_merge is True

        # Run SettleFeature
        settle_stage = SettleFeatureStage(log)
        settle_stage.run_settle(ctx, feature_id="feat-1", disposition="kept")

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_passed" in types
        assert "settle_feature_finalized" in types
        assert "settle_cosmetic_queued" in types

        # Verify report file
        report = (tmp_path / ".haileris" / "settle" / "feat-1.md").read_text()
        assert "feat-1" in report
        assert "kept" in report