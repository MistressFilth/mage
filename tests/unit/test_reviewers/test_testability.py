"""Tests for the testability reviewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.testability import TestabilityReviewer


@pytest.fixture
def fake_reviewer():
    canned = ReviewerVerdict(
        dimension="testability",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="testability@v1",
    )
    return TestabilityReviewer(model=TestModel(custom_output_args=canned))


def test_dimension_is_testability():
    assert TestabilityReviewer.dimension == "testability"


def test_run_returns_verdict(tmp_path, fake_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = fake_reviewer.run(
        draft=draft,
        spec_context={},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "testability"
    assert verdict.outcome in ("pass", "fail")
