"""Tests for IncrementQualityReviewer (per-loop-only reviewer)."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.artifacts.verdict import ReviewerVerdict


class TestIncrementQualityReviewer:
    def test_dimension_classvar(self):
        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )
        assert IncrementQualityReviewer.dimension == "increment_quality"

    def test_system_prompt_mentions_three_routes(self):
        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )
        prompt = IncrementQualityReviewer(system_prompt_only=True)._system_prompt()
        assert "spec" in prompt
        assert "code" in prompt
        assert "cosmetic" in prompt

    def test_run_with_canned_testmodel(self):
        from pydantic_ai.models.test import TestModel

        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )

        canned = ReviewerVerdict(
            dimension="increment_quality",
            outcome="pass",
            draft_hash="x",
            reviewed_at=datetime.now(UTC),
            reviewer_id="increment_quality@v1",
            findings=[],
        )
        reviewer = IncrementQualityReviewer(model=TestModel(custom_output_args=canned))
        # system_prompt_only flag means we don't run the agent
        assert reviewer.dimension == "increment_quality"
