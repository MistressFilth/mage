"""Tests for SettleFeatureStage (cosmetic queue + report)."""

from __future__ import annotations


class TestSettleFeatureStage:
    def test_aggregates_cosmetic_queue(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.inspect import CosmeticItem

        log = EventsLog(tmp_path / "events.jsonl")
        item = CosmeticItem(
            sub_bid="00000-0",
            scenario_name="happy",
            location="Given step",
            text="Rephrase for clarity",
            proposed_by="increment_quality",
        )
        mapping = MappingArtifact(project_id="feat-1").append_cosmetic(item)
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=mapping,
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        stage = SettleFeatureStage(log)
        stage.run_settle(
            ctx,
            feature_id="feat-1",
            disposition="kept",
        )

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "settle_feature_started" in types
        assert "settle_cosmetic_queued" in types
        assert "settle_feature_finalized" in types

    def test_writes_settle_report(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        stage = SettleFeatureStage(log)
        stage.run_settle(ctx, feature_id="feat-1", disposition="merged")

        report_path = tmp_path / ".haileris" / "settle" / "feat-1.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "feat-1" in content
        assert "merged" in content
