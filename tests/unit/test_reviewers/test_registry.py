"""Tests for reviewer registry + aggregation logic."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.artifacts.verdict import (
    ReviewerAggregate,
    ReviewerFinding,
    ReviewerVerdict,
)
from mage.verification.reviewers.registry import (
    aggregate_verdicts,
    default_reviewer_registry,
    feature_reviewer_registry,
)


def test_default_registry_has_all_7_dimensions():
    registry = default_reviewer_registry()
    expected = {
        "spec_compliance",
        "scenario_clarity",
        "step_grammar",
        "testability",
        "determinism",
        "naming_idiom",
        "lifecycle_tags",
    }
    assert set(registry.keys()) == expected


def test_aggregate_all_pass_yields_approved():
    verdicts = {
        d: ReviewerVerdict(
            dimension=d,
            outcome="pass",
            draft_hash="h",
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{d}@v1",
        )
        for d in default_reviewer_registry()
    }
    agg = aggregate_verdicts(verdicts, iteration=1)
    assert isinstance(agg, ReviewerAggregate)
    assert agg.decision == "approved"
    assert all(s.outcome == "pass" for s in agg.per_dimension.values())


def test_aggregate_any_fail_yields_needs_refactor():
    verdicts = {
        d: ReviewerVerdict(
            dimension=d,
            outcome="pass",
            draft_hash="h",
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{d}@v1",
        )
        for d in default_reviewer_registry()
    }
    verdicts["scenario_clarity"] = ReviewerVerdict(
        dimension="scenario_clarity",
        outcome="fail",
        draft_hash="h",
        reviewed_at=datetime.now(UTC),
        reviewer_id="scenario_clarity@v1",
        findings=[
            ReviewerFinding(
                id="f-1",
                severity="major",
                location="line 3",
                issue="ambiguous step",
                rationale="'it' has no antecedent.",
            ),
        ],
    )
    agg = aggregate_verdicts(verdicts, iteration=1)
    assert agg.decision == "needs_refactor"
    assert agg.per_dimension["scenario_clarity"].findings_count == 1
    assert agg.per_dimension["spec_compliance"].outcome == "pass"


def test_aggregate_stores_findings_count():
    verdicts = {
        d: ReviewerVerdict(
            dimension=d,
            outcome="fail",
            draft_hash="h",
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{d}@v1",
            findings=[
                ReviewerFinding(
                    id="f-1",
                    severity="minor",
                    location="line 1",
                    issue="x",
                    rationale="y",
                ),
                ReviewerFinding(
                    id="f-2",
                    severity="minor",
                    location="line 2",
                    issue="x",
                    rationale="y",
                ),
            ],
        )
        for d in default_reviewer_registry()
    }
    agg = aggregate_verdicts(verdicts, iteration=1)
    assert all(s.findings_count == 2 for s in agg.per_dimension.values())
    assert agg.decision == "needs_refactor"


class TestFeatureReviewerRegistry:
    def test_feature_reviewer_registry_has_eight_dimensions(self):
        from pydantic_ai.models.test import TestModel

        registry = feature_reviewer_registry(model=TestModel())
        dims = sorted(r.dimension for r in registry)
        assert dims == sorted(
            [
                "cross_scenario",
                "determinism",
                "lifecycle_tags",
                "naming_idiom",
                "scenario_clarity",
                "spec_compliance",
                "step_grammar",
                "testability",
            ]
        )

    def test_feature_reviewer_registry_uses_factory_without_caching(self):
        from pydantic_ai.models.test import TestModel

        calls = []

        def factory():
            calls.append(True)
            return TestModel()

        first = feature_reviewer_registry(model_factory=factory)
        second = feature_reviewer_registry(model_factory=factory)

        assert len(calls) == 16
        assert first[0] is not second[0]
