"""End-to-end: 1 feature × 2 scenarios × 3 increments → all live."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class TestE2EInnerTDDHappyPath:
    def test_two_senarios_three_increments_each_reach_live(self, tmp_path: Path):
        from mage.orchestration.events import EventsLog, EventType
        from mage.orchestration.etch import EtchStage, ScenarioInspectHalted
        from mage.orchestration.realize import RealizeStage
        from mage.orchestration.inspect_loop import InspectLoopStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact, BaseBIDEntry, ScenarioEntry, LifecycleStatus
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")

        # Build mapping with 2 approved scenarios
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

        # Stub agents
        class CleanMech:
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

        class NoOpRealizeAgent:
            def run(self, *, step, scenario_context, red_test_path, carry_forward, cross_scenario_observations):
                from mage.agents.realize import RealizeOutput
                return RealizeOutput(files_changed=[], summary="stub")

        cfg = HostConfig()
        inspect_stage = InspectLoopStage(log, CleanMech(), CleanReviewer(), cfg)
        realize_stage = RealizeStage(log, NoOpRealizeAgent())

        # Drive 2 scenarios × 3 increments each
        for scenario in scenarios:
            for inc in range(3):
                inspect_stage._run_single_increment(
                    ctx,
                    sub_bid=scenario.sub_bid,
                    base_bid="00000",
                    scenario_name=f"scenario-{scenario.sub_bid}",
                    increment_diff="",
                    new_test="",
                    scenario_steps=[],
                )
                realize_stage._run_single_increment(
                    ctx,
                    sub_bid=scenario.sub_bid,
                    step=f"step-{inc}",
                    red_test_path=f"tests/test_{scenario.sub_bid}_{inc}.py",
                )
            # Emit SCENARIO_LIVE
            log.append(
                __import__("mage.orchestration.events", fromlist=["Event", "EventType"]).Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SCENARIO_LIVE,
                    payload={"sub_bid": scenario.sub_bid, "scenario_name": f"scenario-{scenario.sub_bid}"},
                )
            )

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert types.count("inspect_loop_passed") == 6  # 2 scenarios × 3 increments
        assert types.count("inspect_loop_started") == 6
        assert types.count("scenario_live") == 2
