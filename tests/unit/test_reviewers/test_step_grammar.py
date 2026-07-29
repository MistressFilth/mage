"""Tests for the step_grammar reviewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.step_grammar import StepGrammarReviewer


@pytest.fixture
def step_grammar_reviewer():
    canned = ReviewerVerdict(
        dimension="step_grammar",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="step_grammar@v1",
    )
    return StepGrammarReviewer(model=TestModel(custom_output_args=canned))


def test_dimension_is_step_grammar():
    assert StepGrammarReviewer.dimension == "step_grammar"


def test_run_emits_reviewerverdict(tmp_path, step_grammar_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = step_grammar_reviewer.run(
        draft=draft,
        spec_context={},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "step_grammar"
    assert verdict.outcome in ("pass", "fail")