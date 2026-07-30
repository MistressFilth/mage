"""Tests for the lifecycle_tags reviewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer


@pytest.fixture
def fake_reviewer():
    canned = ReviewerVerdict(
        dimension="lifecycle_tags",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="lifecycle_tags@v1",
    )
    return LifecycleTagsReviewer(model=TestModel(custom_output_args=canned))


def test_dimension_is_lifecycle_tags():
    assert LifecycleTagsReviewer.dimension == "lifecycle_tags"


@pytest.mark.asyncio
async def test_run_returns_verdict(tmp_path, fake_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = await fake_reviewer.run(
        draft=draft,
        spec_context={},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "lifecycle_tags"
    assert verdict.outcome in ("pass", "fail")
