"""Reviewer registry + verdict aggregation logic."""

from __future__ import annotations

from datetime import datetime, UTC

from mage.artifacts.verdict import (
    DimensionSummary,
    ReviewerAggregate,
    ReviewerVerdict,
)
from mage.verification.reviewers.base import ReviewerAgent
from mage.verification.reviewers.determinism import DeterminismReviewer
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
from mage.verification.reviewers.step_grammar import StepGrammarReviewer
from mage.verification.reviewers.testability import TestabilityReviewer


def default_reviewer_registry() -> dict[str, type[ReviewerAgent]]:
    """Return the 7 reviewer dimensions → their agent classes."""
    return {
        "spec_compliance": SpecComplianceReviewer,
        "scenario_clarity": ScenarioClarityReviewer,
        "step_grammar": StepGrammarReviewer,
        "testability": TestabilityReviewer,
        "determinism": DeterminismReviewer,
        "naming_idiom": NamingIdiomReviewer,
        "lifecycle_tags": LifecycleTagsReviewer,
    }


def feature_reviewer_registry() -> list[ReviewerAgent]:
    """Return the end-of-feature Inspect reviewers (7 from Plan 3 + cross_scenario).

    Distinct from default_reviewer_registry (which is the Inscribe 7-reviewer set).
    Both share dimension names for the 7 original; cross_scenario is added here.
    """
    if not getattr(feature_reviewer_registry, "_cache", None):
        from pydantic_ai.models.test import TestModel

        from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer

        # Use a TestModel placeholder — InspectFeatureStage will inject real models
        # based on host config in production. Tests pass canned TestModels.
        # (A bare MagicMock would fail pydantic_ai's model-name validation.)
        model = TestModel()

        feature_reviewer_registry._cache = [
            SpecComplianceReviewer(model=model),
            ScenarioClarityReviewer(model=model),
            StepGrammarReviewer(model=model),
            TestabilityReviewer(model=model),
            DeterminismReviewer(model=model),
            NamingIdiomReviewer(model=model),
            LifecycleTagsReviewer(model=model),
            CrossScenarioReviewer(model=model),
        ]
    return list(feature_reviewer_registry._cache)


def aggregate_verdicts(
    per_dimension_verdicts: dict[str, ReviewerVerdict],
    iteration: int,
) -> ReviewerAggregate:
    """Aggregate per-dimension verdicts into a single ReviewerAggregate.

    Decision rule:
    - all 7 dimensions pass → 'approved'
    - any dimension fails → 'needs_refactor'

    I4: this function intentionally never produces 'needs_human_review'.
    That decision belongs to the downstream decision-gate stage (Plan 6),
    which evaluates the aggregate alongside other context (escalation
    history, severity of findings, etc.) to decide whether a human must
    weigh in. Aggregating reviewers should not pre-empt that stage.
    """
    per_dimension: dict[str, DimensionSummary] = {}
    any_fail = False
    for dimension, verdict in per_dimension_verdicts.items():
        if verdict.outcome == "fail":
            any_fail = True
        per_dimension[dimension] = DimensionSummary(
            outcome=verdict.outcome,
            reviewer_verdict_ref=f".haileris/verdicts/{verdict.draft_hash}/{verdict.dimension}.yaml",
            findings_count=len(verdict.findings),
        )

    decision = "needs_refactor" if any_fail else "approved"
    reasoning = (
        f"all 7 dimensions passed" if decision == "approved"
        else f"at least one dimension failed; iteration={iteration}"
    )

    # The aggregate uses the first verdict's draft_hash (they should all match).
    draft_hash = next(iter(per_dimension_verdicts.values())).draft_hash

    return ReviewerAggregate(
        draft_hash=draft_hash,
        aggregated_at=datetime.now(UTC),
        iteration=iteration,
        per_dimension=per_dimension,
        decision=decision,
        reasoning=reasoning,
    )
