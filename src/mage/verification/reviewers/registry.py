"""Reviewer registry + verdict aggregation logic."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from mage.artifacts.verdict import (
    DimensionSummary,
    ReviewerAggregate,
    ReviewerVerdict,
)
from mage.host_project_config import MageTomlConfig
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
    mage_toml: MageTomlConfig | None = None,
    providers: dict[str, Any] | None = None,
    default_provider: str = "anthropic",
    events_log: Any | None = None,
) -> list[ReviewerAgent]:
    """Build the end-of-feature reviewer set with an injected model.

    Exactly one of ``model``, ``model_factory``, or ``mage_toml`` is required.
    A factory is useful for providers that require an independent model
    instance per agent. ``mage_toml`` resolves the default-tier model through
    the P31 provider chain — reviewers have no per-agent override, so all eight
    share the one resolved instance. Reviewers are rebuilt on every call so
    host/model changes cannot be hidden by process-wide cached agents.

    The ``mage_toml`` path passes ``events_log`` straight to
    :meth:`mage.host_project_config.MageTomlConfig.default_model_instance`,
    which appends events synchronously. Callers that pass the real async
    :class:`mage.orchestration.events.EventsLog` will end up with an
    unawaited coroutine — prefer :func:`feature_reviewer_registry_async`
    in any path that has a running event loop.
    """
    supplied = [s for s in (model, model_factory, mage_toml) if s is not None]
    if len(supplied) != 1:
        raise ValueError("provide exactly one of model, model_factory, or mage_toml")

    from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer

    if mage_toml is not None:
        resolved, _, _ = mage_toml.default_model_instance(
            providers=providers or {},
            default_provider=default_provider,
            env=dict(os.environ),
            events_log=events_log,
        )

        def next_model() -> Any:
            return resolved
    else:

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


async def feature_reviewer_registry_async(
    *,
    mage_toml: MageTomlConfig,
    providers: dict[str, Any] | None = None,
    default_provider: str = "anthropic",
    events_log: Any | None = None,
) -> list[ReviewerAgent]:
    """Async variant of :func:`feature_reviewer_registry` for the ``mage_toml`` path.

    Resolves the default-tier model through :func:`resolve_model_logged` so
    ``PROVIDER_RESOLVED`` (and ``PROVIDER_RESOLVED_FAILED`` on error) are
    flushed through the real async :class:`EventsLog` before the reviewers
    are constructed. Prefer this over the sync ``feature_reviewer_registry``
    in any path that has a running event loop.
    """
    from mage.host_project_config import resolve_model_logged
    from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer

    resolved, _, _ = await resolve_model_logged(
        mage_toml,
        None,
        providers=providers or {},
        default_provider=default_provider,
        env=dict(os.environ),
        events_log=events_log,
    )

    def next_model() -> Any:
        return resolved

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
            reviewer_verdict_ref=f".mage/verdicts/{verdict.draft_hash}/{verdict.dimension}.yaml",
            findings_count=len(verdict.findings),
        )

    decision = "needs_refactor" if any_fail else "approved"
    reasoning = (
        "all 7 dimensions passed"
        if decision == "approved"
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
