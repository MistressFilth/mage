"""Tests for InspectFeatureStage end-of-feature orchestration."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact
from mage.artifacts.verdict import ReviewerFinding, ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.orchestration.inspect_feature import InspectFeatureStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig, default_check_set
from mage.verification.mechanical import MechanicalVerifier


class CleanMechanicalVerifier:
    def verify(self, draft, mapping):
        return []


def make_context(
    tmp_path, *, mapping: MappingArtifact | None = None
) -> PipelineContext:
    log = EventsLog(tmp_path / "events.jsonl")
    return PipelineContext(
        project_dir=tmp_path,
        mapping=mapping or MappingArtifact(project_id="feat-1"),
        events_log=log,
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


def make_scenario(
    sub_bid: str = "000000",
    name: str = "happy",
    body: str = "Given a user\nWhen they act\nThen it succeeds",
    *,
    tags: list[str] | None = None,
    feature_path=None,
) -> dict:
    scenario = {
        "sub_bid": sub_bid,
        "base_bid": sub_bid[:5],
        "scenario_name": name,
        "gherkin_body": body,
        "tags": tags or ["@status-live"],
    }
    if feature_path is not None:
        scenario["feature_path"] = feature_path
    return scenario


def make_reviewer(
    dimension: str,
    *,
    findings: list[ReviewerFinding] | None = None,
    outcome: str | None = None,
):
    class Reviewer:
        async def run(self, **kwargs):
            reviewer_findings = findings or []
            return ReviewerVerdict(
                dimension=dimension,
                outcome=outcome or ("fail" if reviewer_findings else "pass"),
                draft_hash="",
                reviewed_at=datetime.now(UTC),
                reviewer_id=f"{dimension}@v1",
                findings=reviewer_findings,
            )

    Reviewer.dimension = dimension
    return Reviewer()


class TestInspectFeatureStage:
    @pytest.mark.asyncio
    async def test_passes_when_all_reviewers_clean_and_attaches_artifact(
        self, tmp_path
    ):
        context = make_context(tmp_path)
        reviewers = [
            make_reviewer(dimension)
            for dimension in (
                "spec_compliance",
                "scenario_clarity",
                "step_grammar",
                "testability",
                "determinism",
                "naming_idiom",
                "lifecycle_tags",
                "cross_scenario",
            )
        ]
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=reviewers,
            mechanical_verifier=CleanMechanicalVerifier(),
            host_config=HostConfig(),
        )

        artifact = await stage.run_pass(
            context,
            feature_id="feat-1",
            scenarios=[make_scenario()],
        )

        assert artifact.ready_to_merge is True
        assert artifact.iteration == 1
        assert context.mapping.feature_status == "inspect_passed"
        assert context.mapping.feature_inspect is not None
        assert context.mapping.feature_inspect["inspect_sha256"]
        assert MappingArtifact.load(tmp_path / "mapping.yaml") == context.mapping
        event_types = [
            event.event_type.value for event in context.events_log.read_all()
        ]
        assert "inspect_feature_started" in event_types
        assert "inspect_feature_finalized" in event_types
        assert "inspect_feature_passed" in event_types

    @pytest.mark.asyncio
    async def test_critical_finding_marks_feature_pending(self, tmp_path):
        finding = ReviewerFinding(
            id="f-1",
            severity="critical",
            location="000000",
            issue="Critical issue",
            rationale="Breaks the spec",
            suggestion="Fix",
            citations=["000000"],
        )
        context = make_context(tmp_path)
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=[make_reviewer("spec_compliance", findings=[finding])],
            mechanical_verifier=CleanMechanicalVerifier(),
            host_config=HostConfig(),
        )

        artifact = await stage.run_pass(
            context,
            feature_id="feat-1",
            scenarios=[make_scenario()],
        )

        assert artifact.ready_to_merge is False
        assert len(artifact.critical) == 1
        assert context.mapping.feature_status == "inspect_pending"

    @pytest.mark.asyncio
    async def test_reviewer_errors_fail_closed(self, tmp_path):
        class BrokenReviewer:
            dimension = "spec_compliance"

            async def run(self, **kwargs):
                raise RuntimeError("review backend unavailable")

        context = make_context(tmp_path)
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=[BrokenReviewer()],
            mechanical_verifier=CleanMechanicalVerifier(),
            host_config=HostConfig(),
        )

        with pytest.raises(RuntimeError, match="review backend unavailable"):
            await stage.run_pass(
                context,
                feature_id="feat-1",
                scenarios=[make_scenario()],
            )

        assert not any(
            event.event_type.value == "inspect_feature_passed"
            for event in context.events_log.read_all()
        )

    @pytest.mark.asyncio
    async def test_real_registry_runs_through_stage_with_injected_model(self, tmp_path):
        from pydantic_ai.models.test import TestModel

        from mage.verification.reviewers.registry import feature_reviewer_registry

        canned = ReviewerVerdict(
            dimension="placeholder",
            outcome="pass",
            draft_hash="x",
            reviewed_at=datetime.now(UTC),
            reviewer_id="placeholder@v1",
            findings=[],
        )
        reviewers = feature_reviewer_registry(
            model=TestModel(custom_output_args=canned)
        )
        context = make_context(tmp_path)
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=reviewers,
            mechanical_verifier=MechanicalVerifier(checks=[]),
            host_config=HostConfig(),
        )

        artifact = await stage.run_pass(
            context,
            feature_id="feat-1",
            scenarios=[make_scenario()],
        )

        assert artifact.ready_to_merge is True
        assert {item["dimension"] for item in artifact.per_reviewer} == {
            "mechanical",
            "spec_compliance",
            "scenario_clarity",
            "step_grammar",
            "testability",
            "determinism",
            "naming_idiom",
            "lifecycle_tags",
            "cross_scenario",
        }

    @pytest.mark.asyncio
    async def test_full_default_mechanical_precheck_blocks_llm_reviewers(
        self, tmp_path
    ):
        feature_path = tmp_path / "happy.feature"
        feature_path.write_text(
            "@status-live\nScenario: happy\n"
            "Given a user\nWhen they act\nThen it succeeds\n",
            encoding="utf-8",
        )
        mapping = MappingArtifact(
            project_id="feat-1",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="behavior",
                    behavior_description="description",
                )
            ],
        )
        context = make_context(tmp_path, mapping=mapping)
        verifier = MechanicalVerifier(
            checks=default_check_set(
                registered_tags={"@status-live"},
                step_patterns=[re.compile(r"^(Given|When|Then) ")],
            )
        )
        reviewer_calls = []

        class RecordingReviewer:
            dimension = "spec_compliance"

            async def run(self, **kwargs):
                reviewer_calls.append(True)
                return await make_reviewer("spec_compliance").run()

        stage = InspectFeatureStage(
            context.events_log,
            reviewers=[RecordingReviewer()],
            mechanical_verifier=verifier,
            host_config=HostConfig(),
        )
        invalid = make_scenario(
            body="Given a user\nThen it succeeds",
            feature_path=feature_path,
        )

        artifact = await stage.run_pass(
            context,
            feature_id="feat-1",
            scenarios=[invalid],
        )

        assert reviewer_calls == []
        assert artifact.ready_to_merge is False
        assert artifact.critical[0]["id"].startswith("mechanical:")
        mechanical = next(
            item for item in artifact.per_reviewer if item["dimension"] == "mechanical"
        )
        assert mechanical["outcome"] == "fail"
        assert mechanical["findings"]

    @pytest.mark.asyncio
    async def test_reviews_every_scenario_with_real_body_and_tags(self, tmp_path):
        reviewed = []
        cross_scenarios = []

        class RecordingReviewer:
            dimension = "scenario_clarity"

            async def run(self, *, draft, spec_context, **kwargs):
                reviewed.append(
                    (
                        draft.name,
                        draft.gherkin_body,
                        draft.tags,
                        spec_context["sub_bid"],
                    )
                )
                return await make_reviewer("scenario_clarity").run()

        class CrossReviewer:
            dimension = "cross_scenario"

            async def run(self, *, scenarios, **kwargs):
                cross_scenarios.extend(scenarios)
                return await make_reviewer("cross_scenario").run()

        scenarios = [
            make_scenario("000000", "first", "Given first\nWhen A\nThen one"),
            make_scenario("000001", "second", "Given second\nWhen B\nThen two"),
            make_scenario("000002", "third", "Given third\nWhen C\nThen three"),
        ]
        context = make_context(tmp_path)
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=[RecordingReviewer(), CrossReviewer()],
            mechanical_verifier=CleanMechanicalVerifier(),
            host_config=HostConfig(),
        )

        await stage.run_pass(context, feature_id="feat-1", scenarios=scenarios)

        assert reviewed == [
            (
                scenario["scenario_name"],
                scenario["gherkin_body"],
                scenario["tags"],
                scenario["sub_bid"],
            )
            for scenario in scenarios
        ]
        assert cross_scenarios == scenarios

    @pytest.mark.asyncio
    async def test_minor_findings_append_cosmetic_queue_and_cross_field_is_findings(
        self, tmp_path
    ):
        finding = ReviewerFinding(
            id="minor-1",
            severity="minor",
            location="Given step",
            issue="Could be clearer",
            rationale="Wording only",
            suggestion="Rephrase the Given",
            citations=["000000"],
        )
        context = make_context(tmp_path)
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=[make_reviewer("cross_scenario", findings=[finding])],
            mechanical_verifier=CleanMechanicalVerifier(),
            host_config=HostConfig(),
        )

        artifact = await stage.run_pass(
            context,
            feature_id="feat-1",
            scenarios=[make_scenario()],
        )

        assert artifact.cross_scenario == [finding.model_dump(mode="json")]
        assert context.mapping.cosmetic_findings == [
            {
                "feature_id": "feat-1",
                "sub_bid": "000000",
                "scenario_name": "happy",
                "location": "Given step",
                "text": "Rephrase the Given",
                "proposed_by": "cross_scenario",
            }
        ]
        assert MappingArtifact.load(tmp_path / "mapping.yaml") == context.mapping

    @pytest.mark.asyncio
    async def test_important_findings_dispatch_one_brief_and_retry_until_clean(
        self, tmp_path
    ):
        findings = [
            ReviewerFinding(
                id=f"important-{index}",
                severity="major",
                location="code",
                issue=f"Issue {index}",
                rationale="Needs a targeted fix",
                suggestion=f"Fix {index}",
                citations=["000000"],
            )
            for index in (1, 2)
        ]
        reviewer_calls = 0
        dispatches = []

        class ImportantThenCleanReviewer:
            dimension = "testability"

            async def run(self, **kwargs):
                nonlocal reviewer_calls
                reviewer_calls += 1
                return await make_reviewer(
                    "testability",
                    findings=findings if reviewer_calls == 1 else [],
                ).run()

        def dispatch_fix_wave(**kwargs):
            dispatches.append(kwargs)

        context = make_context(tmp_path)
        stage = InspectFeatureStage(
            context.events_log,
            reviewers=[ImportantThenCleanReviewer()],
            mechanical_verifier=CleanMechanicalVerifier(),
            fix_wave_dispatcher=dispatch_fix_wave,
            host_config=HostConfig(eof_max_iterations=3),
        )

        artifact = await stage.run_pass(
            context,
            feature_id="feat-1",
            scenarios=[make_scenario()],
        )

        assert artifact.ready_to_merge is True
        assert artifact.iteration == 2
        assert context.iteration == 2
        assert reviewer_calls == 2
        assert len(dispatches) == 1
        assert "important-1" in dispatches[0]["brief"]
        assert "important-2" in dispatches[0]["brief"]
        fix_events = [
            event
            for event in context.events_log.read_all()
            if event.event_type.value == "fix_wave_dispatched"
        ]
        assert len(fix_events) == 1
        assert fix_events[0].payload["iteration"] == 1
