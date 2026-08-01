"""Tests for HostConfig.enabled_reviewers filter on InspectFeatureStage.

Mirrors the InscribeStage predicate: None = all, [] = none, list = subset.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.inspect_feature import InspectFeatureStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig


class CleanMechanicalVerifier:
    def verify(self, draft, mapping):
        return []


def make_context(tmp_path) -> PipelineContext:
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext

    log = EventsLog(tmp_path / "events.jsonl")
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="feat-1"),
        events_log=log,
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


def make_scenario(
    sub_bid: str = "000000",
    name: str = "happy",
) -> dict:
    return {
        "sub_bid": sub_bid,
        "base_bid": sub_bid[:5],
        "scenario_name": name,
        "gherkin_body": "Given a user\nWhen they act\nThen it succeeds",
        "tags": ["@status-live"],
    }


class RecordingReviewer:
    """Records each .run(...) call into a shared list. Signature-flexible."""

    def __init__(self, dimension: str, log: list[str]) -> None:
        self.dimension = dimension
        self._log = log

    async def run(self, **kwargs) -> ReviewerVerdict:  # type: ignore[no-untyped-def]
        self._log.append(self.dimension)
        return ReviewerVerdict(
            dimension=self.dimension,
            outcome="pass",
            draft_hash="",
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{self.dimension}@v1",
            findings=[],
        )


@pytest.mark.asyncio
async def test_enabled_reviewers_none_runs_all_reviewers(tmp_path):
    context = make_context(tmp_path)
    calls: list[str] = []
    reviewers = [
        RecordingReviewer("spec_compliance", calls),
        RecordingReviewer("testability", calls),
        RecordingReviewer("lifecycle_tags", calls),
        RecordingReviewer("cross_scenario", calls),
    ]
    stage = InspectFeatureStage(
        context.events_log,
        reviewers=reviewers,
        mechanical_verifier=CleanMechanicalVerifier(),
        host_config=HostConfig(enabled_reviewers=None),
    )

    await stage.run_pass(
        context,
        feature_id="feat-1",
        scenarios=[make_scenario()],
    )

    # Scenario reviewers fire once per scenario; cross fires once.
    assert calls.count("spec_compliance") == 1
    assert calls.count("testability") == 1
    assert calls.count("lifecycle_tags") == 1
    assert calls.count("cross_scenario") == 1


@pytest.mark.asyncio
async def test_enabled_reviewers_subset_runs_only_listed(tmp_path):
    context = make_context(tmp_path)
    calls: list[str] = []
    reviewers = [
        RecordingReviewer("spec_compliance", calls),
        RecordingReviewer("testability", calls),
        RecordingReviewer("lifecycle_tags", calls),
        RecordingReviewer("cross_scenario", calls),
    ]
    stage = InspectFeatureStage(
        context.events_log,
        reviewers=reviewers,
        mechanical_verifier=CleanMechanicalVerifier(),
        host_config=HostConfig(enabled_reviewers=["spec_compliance", "testability"]),
    )

    await stage.run_pass(
        context,
        feature_id="feat-1",
        scenarios=[make_scenario()],
    )

    assert "spec_compliance" in calls
    assert "testability" in calls
    assert "lifecycle_tags" not in calls
    assert "cross_scenario" not in calls


@pytest.mark.asyncio
async def test_enabled_reviewers_cross_only_skips_scenario_loop(tmp_path):
    context = make_context(tmp_path)
    calls: list[str] = []
    reviewers = [
        RecordingReviewer("spec_compliance", calls),
        RecordingReviewer("testability", calls),
        RecordingReviewer("cross_scenario", calls),
    ]
    stage = InspectFeatureStage(
        context.events_log,
        reviewers=reviewers,
        mechanical_verifier=CleanMechanicalVerifier(),
        host_config=HostConfig(enabled_reviewers=["cross_scenario"]),
    )

    await stage.run_pass(
        context,
        feature_id="feat-1",
        scenarios=[make_scenario()],
    )

    assert "cross_scenario" in calls
    assert "spec_compliance" not in calls
    assert "testability" not in calls


@pytest.mark.asyncio
async def test_enabled_reviewers_empty_list_runs_none(tmp_path):
    context = make_context(tmp_path)
    calls: list[str] = []
    reviewers = [
        RecordingReviewer("spec_compliance", calls),
        RecordingReviewer("cross_scenario", calls),
    ]
    stage = InspectFeatureStage(
        context.events_log,
        reviewers=reviewers,
        mechanical_verifier=CleanMechanicalVerifier(),
        host_config=HostConfig(enabled_reviewers=[]),
    )

    await stage.run_pass(
        context,
        feature_id="feat-1",
        scenarios=[make_scenario()],
    )

    assert calls == []


@pytest.mark.asyncio
async def test_enabled_reviewers_unknown_dimension_silently_filtered(tmp_path):
    context = make_context(tmp_path)
    calls: list[str] = []
    reviewers = [
        RecordingReviewer("spec_compliance", calls),
        RecordingReviewer("cross_scenario", calls),
    ]
    stage = InspectFeatureStage(
        context.events_log,
        reviewers=reviewers,
        mechanical_verifier=CleanMechanicalVerifier(),
        host_config=HostConfig(enabled_reviewers=["does_not_exist"]),
    )

    await stage.run_pass(
        context,
        feature_id="feat-1",
        scenarios=[make_scenario()],
    )

    assert calls == []
