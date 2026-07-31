"""Tests for the scenario_clarity reviewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer


@pytest.fixture
def scenario_clarity_reviewer():
    canned = ReviewerVerdict(
        dimension="scenario_clarity",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="scenario_clarity@v1",
    )
    return ScenarioClarityReviewer(model=TestModel(custom_output_args=canned))


def test_dimension_is_scenario_clarity():
    assert ScenarioClarityReviewer.dimension == "scenario_clarity"


@pytest.mark.asyncio
async def test_run_emits_reviewerverdict(tmp_path, scenario_clarity_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="login", gherkin_body="Given ...")

    verdict = await scenario_clarity_reviewer.run(
        draft=draft,
        spec_context={"behavior_name": "auth"},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "scenario_clarity"
    assert verdict.outcome in ("pass", "fail")
