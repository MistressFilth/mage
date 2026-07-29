"""Reviewer registry + verdict aggregation logic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

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


def feature_reviewer_registry(
    *,
    model: Any | None = None,
    model_factory: Callable[[], Any] | None = None,
) -> list[ReviewerAgent]:
    """Build the end-of-feature reviewer set with an injected model.

    Exactly one of ``model`` or ``model_factory`` is required. A factory is useful
    for providers that require an independent model instance per agent. Reviewers
    are rebuilt on every call so host/model changes cannot be hidden by process-wide
    cached agents.
    """
    if (model is None) == (model_factory is None):
        raise ValueError("provide exactly one of model or model_factory")

    from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer

    def next_model() -> Any:
        return model_factory() if model_factory is not None else model

    return [
        SpecComplianceReviewer(model=next_model()),
        ScenarioClarityReviewer(model=next_model()),
        StepGrammarReviewer(model=next_model()),
        TestabilityReviewer(model=next_model()),
        DeterminismReviewer(model=next_model()),
        NamingIdiomReviewer(model=next_model()),
        LifecycleTagsReviewer(model=next_model()),
        CrossScenarioReviewer(model=next_model()),
    ]


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
