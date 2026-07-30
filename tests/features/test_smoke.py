"""End-to-end smoke test for Plan 1: foundation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.graph import PipelineGraph
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.persistence import FileStatePersistence
from mage.verification.host_overrides import default_check_set, load_host_config
from mage.verification.mechanical import (
    MechanicalVerifier,
    ScenarioDraft,
)


class CountingStage(StageNode):
    """A trivial stage that bumps the iteration counter."""

    name = "count"

    async def _run(self, context: PipelineContext) -> PipelineContext:
        return context.model_copy(update={"iteration": context.iteration + 1})


class TestFoundationEndToEnd:
    @pytest.mark.asyncio
    async def test_full_flow(self, tmp_project_dir: Path):
        # 1. Mapping artifact: create with one base BID.
        mapping = MappingArtifact(
            schema_version=1,
            project_id="smoke",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="smoke behavior",
                    behavior_description="end-to-end test behavior",
                    scenarios=[
                        ScenarioEntry(
                            sub_bid="A",
                            scenario_text_hash="hashA",
                            lifecycle_status=LifecycleStatus.LIVE,
                            supersedes=None,
                            superseded_by=None,
                            tests=["test_smoke::test_full_flow"],
                            derivations=["tests/test_smoke.py"],
                        )
                    ],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        mapping_path = tmp_project_dir / "mapping.yaml"
        await mapping.save(mapping_path)
        loaded = MappingArtifact.load(mapping_path)
        assert loaded.project_id == "smoke"
        assert loaded.next_base_bid().value == "00001"

        # 2. Persistence: save and load state.
        state_dir = tmp_project_dir / "state"
        persistence = FileStatePersistence(state_dir, PipelineContext)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=loaded,
            events_log=EventsLog(tmp_project_dir / "events.jsonl"),
            iteration=5,
        )
        persistence.save_state(ctx)
        restored = persistence.load_state()
        assert restored is not None
        assert restored.iteration == 5

        # 3. Events log: append a few events, read them back.
        log = EventsLog(tmp_project_dir / "events.jsonl")
        await log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.STAGE_STARTED,
                payload={"stage": "smoke"},
            )
        )
        events = log.read_all()
        assert len(events) >= 1

        # 4. Mechanical verification: build the default check set, run it.
        feature_path = tmp_project_dir / "smoke.feature"
        feature_path.write_text(
            "Feature: Smoke\n\n  Scenario: Valid\n    Given x\n    When y\n    Then z\n"
        )
        checks = default_check_set(
            registered_tags=set(),
            step_patterns=[
                re.compile(r"Given x"),
                re.compile(r"When y"),
                re.compile(r"Then z"),
            ],
        )
        verifier = MechanicalVerifier(checks=checks)
        draft = ScenarioDraft(
            feature_path=feature_path,
            scenario_name="Valid",
            gherkin_text=feature_path.read_text(),
            tags=["@status-live"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x", "When y", "Then z"],
        )
        results = verifier.verify(draft, loaded)
        # GherkinSyntaxCheck, ScenarioNameUniqueCheck, StepDefinitionsResolvableCheck,
        # LifecycleStatusTagPresentCheck, SubBidAssignedCheck, CrossBehaviorTagsValidCheck
        # should pass. TagsRegisteredCheck fails (no registered tags).
        passed = [r for r in results if r.outcome == "pass"]
        failed = [r for r in results if r.outcome == "fail"]
        assert len(passed) >= 5
        assert any(r.name == "tags-registered" for r in failed)

        # 5. Host config: defaults load when no config file.
        config = load_host_config(tmp_project_dir)
        assert config.max_iterations == 3

        # 6. Stage node: run a stage through the graph.
        stage = CountingStage(events_log=log)
        graph = PipelineGraph(stages=[stage, stage], events_log=log)
        result = await graph.run(ctx)
        assert result.iteration == 7  # 5 (from restore) + 2 stages
