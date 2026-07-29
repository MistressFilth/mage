"""Tests for the determinism reviewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.determinism import DeterminismReviewer


@pytest.fixture
def fake_reviewer():
    canned = ReviewerVerdict(
        dimension="determinism",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="determinism@v1",
    )
    return DeterminismReviewer(model=TestModel(custom_output_args=canned))


def test_dimension_is_determinism():
    assert DeterminismReviewer.dimension == "determinism"


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
    assert verdict.dimension == "determinism"
    assert verdict.outcome in ("pass", "fail")
