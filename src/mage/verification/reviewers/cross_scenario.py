"""End-of-feature-only reviewer: CrossScenarioReviewer.

Reviews the whole feature as one unit for cross-scenario issues:
- Shared state leaks (multiple scenarios read/write the same domain object)
- Ordering dependencies (scenarios that must run in a particular order)
- Integration gaps (where two scenarios' domain models touch)
- Cross-scenario naming/tag collisions (drift across scenarios)

Used ONLY by InspectFeatureStage (Plan 5). NOT registered in
default_reviewer_registry (which is the Inscribe 7-reviewer registry).
Added to feature_reviewer_registry (Plan 5 Task 3).
"""

from __future__ import annotations

from typing import ClassVar

from mage.artifacts.verdict import ReviewerVerdict
from mage.verification.reviewers.base import ReviewerAgent


class CrossScenarioReviewer(ReviewerAgent):
    """End-of-feature-only reviewer for cross-scenario issues."""

    dimension: ClassVar[str] = "cross_scenario"

    def __init__(self, model=None, *, system_prompt_only: bool = False) -> None:
        # Build the agent lazily — system_prompt_only is a test helper that
        # skips the Agent() constructor (no model needed).
        self._system_prompt_only = system_prompt_only
        if not system_prompt_only:
            from pydantic_ai import Agent

            self._agent = Agent(
                model, output_type=ReviewerVerdict, system_prompt=self._system_prompt()
            )

    def _system_prompt(self) -> str:
        return (
            "You are a Cross-Scenario Reviewer. Review the WHOLE FEATURE as one unit. "
            "Look for four kinds of issues:\n\n"
            "  1. SHARED STATE LEAKS — multiple scenarios read/write the same "
            "domain object in ways that conflict.\n"
            "  2. ORDERING DEPENDENCIES — scenarios that must run in a particular "
            "order that per-scenario reviews don't observe.\n"
            "  3. INTEGRATION GAPS — where two scenarios' domain models touch but "
            "neither scenario's test exercises the boundary.\n"
            "  4. NAMING/TAG COLLISIONS — naming patterns or tag conventions that "
            "drift across scenarios.\n\n"
            "Each finding has severity (critical/major/minor), location (scenario "
            "name + sub_bid), issue, rationale, and suggestion. "
            "Rationale is mandatory."
        )

    async def run(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        *,
        draft,  # Liskov compat with ReviewerAgent.run; unused at feature scope
        spec_context: dict,  # Liskov compat; unused at feature scope
        mapping,  # Liskov compat; unused at feature scope
        events_log,  # Liskov compat; unused at feature scope
        verdict_path,  # Liskov compat; unused at feature scope
        feature_summary: dict,
        scenarios: list[dict],
    ) -> ReviewerVerdict:
        """Run the reviewer across the whole feature.

        Plan 5's InspectFeatureStage (Task 5) calls this with the full
        feature's scenario set. The signature mirrors `ReviewerAgent.run`
        plus two feature-scoped extras (`feature_summary`, `scenarios`)
        and is therefore Liskov-compatible.
        """
        from datetime import UTC, datetime

        prompt = (
            f"Feature summary: {feature_summary}\n\n"
            f"Scenarios:\n" + "\n".join(f"  {s}" for s in scenarios) + "\n\n"
            "Review for cross-scenario issues per your rubric."
        )

        result = (await self._agent.run(prompt)).output
        # Force the dimension + timestamps (do not trust LLM output for these)
        result_dict = result.model_dump()
        result_dict["dimension"] = self.dimension
        result_dict["reviewed_at"] = datetime.now(UTC)
        result_dict["reviewer_id"] = f"{self.dimension}@v1"
        # Note: draft_hash is not meaningful at feature scope; use a stable placeholder
        result_dict["draft_hash"] = ""
        return ReviewerVerdict.model_validate(result_dict)
