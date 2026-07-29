"""Tests for CrossScenarioReviewer (eof-only reviewer)."""

from __future__ import annotations

from datetime import UTC, datetime


def test_dimension_classvar():
    from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
    assert CrossScenarioReviewer.dimension == "cross_scenario"


def test_system_prompt_mentions_four_foci():
    from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
    prompt = CrossScenarioReviewer(system_prompt_only=True)._system_prompt()
    assert "shared state" in prompt.lower()
    assert "ordering" in prompt.lower()
    assert "integration" in prompt.lower()
    assert "naming" in prompt.lower() or "tag" in prompt.lower()


def test_run_with_canned_testmodel():
    from pydantic_ai.models.test import TestModel
    from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
    from mage.artifacts.verdict import ReviewerVerdict

    canned = ReviewerVerdict(
        dimension="cross_scenario",
        outcome="pass",
        draft_hash="",
        reviewed_at=datetime.now(UTC),
        reviewer_id="cross_scenario@v1",
        findings=[],
    )
    reviewer = CrossScenarioReviewer(model=TestModel(custom_output_args=canned))
    assert reviewer.dimension == "cross_scenario"