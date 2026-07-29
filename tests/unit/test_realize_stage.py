"""Tests for RealizeStage."""

from __future__ import annotations

from datetime import UTC, datetime


class TestCarryForwardInjection:
    def test_realize_pulls_carry_forward_from_mapping(self, tmp_path):
        from mage.agents.realize import RealizeOutput
        from mage.artifacts.inspect import InspectJournalEntry
        from mage.artifacts.mapping import (
            BaseBIDEntry,
            LifecycleStatus,
            MappingArtifact,
            ScenarioEntry,
        )
        from mage.orchestration.events import EventsLog
        from mage.orchestration.nodes import PipelineContext
        from mage.orchestration.realize import RealizeStage

        log = EventsLog(tmp_path / "events.jsonl")
        # Build a mapping with one scenario that has a journal entry
        scenario = ScenarioEntry(
            sub_bid="00000-0",
            scenario_text_hash="abc",
            lifecycle_status=LifecycleStatus.APPROVED,
        )
        mapping = MappingArtifact(
            project_id="p1",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="happy",
                    behavior_description="x",
                    scenarios=[scenario],
                )
            ],
        )
        entry = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="major",
            route="code",
            finding_id="f-1",
            location="src/foo.py:42",
            issue="Missing edge case",
            rationale="Test does not cover empty input",
        )
        mapping = mapping.append_inspect_journal("00000-0", entry)

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=mapping,
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        # Capture the prompt RealizeAgent.run was called with
        captured_prompts = []

        class StubAgent:
            def run(
                self,
                *,
                step,
                scenario_context,
                red_test_path,
                carry_forward,
                cross_scenario_observations,
            ):
                captured_prompts.append(carry_forward)
                return RealizeOutput(files_changed=[], summary="stub")

        stage = RealizeStage(log, agent=StubAgent())
        stage._run_single_increment(
            ctx,
            sub_bid="00000-0",
            step="compute_total",
            red_test_path="tests/test_x.py",
        )

        assert len(captured_prompts) == 1
        assert len(captured_prompts[0]) == 1
        assert captured_prompts[0][0].finding_id == "f-1"
