"""Per-loop-only reviewer: IncrementQualityReviewer.

Reviews the increment diff for code quality, test quality, and design
appropriateness. Tags each finding with one of three routes (spec/code/cosmetic)
per spec R20. Used ONLY by InspectLoopStage (Plan 4). NOT registered in
default_reviewer_registry (which is the Inscribe 7-reviewer registry).
"""

from __future__ import annotations

from typing import ClassVar

from mage.artifacts.inspect import InspectJournalEntry
from mage.artifacts.verdict import ReviewerVerdict
from mage.verification.reviewers.base import ReviewerAgent


class IncrementQualityReviewer(ReviewerAgent):
    """Per-loop-only reviewer for increment-level quality.

    Different from Plan 3's 7 reviewers: prompts are about the diff under
    review, not the scenario text. Findings carry 3-route tagging (R20)
    via the structured `route` field on ReviewerFinding — InspectLoopStage
    reads it directly. No more string-prefix parsing of `suggestion`.
    """

    dimension: ClassVar[str] = "increment_quality"

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
            "You are an Increment Quality Reviewer. Review code diffs for "
            "code quality, test quality, and design appropriateness. "
            "Tag EACH finding with one of three routes:\n\n"
            "  - 'spec': the approved spec is wrong (the increment reveals "
            "the scenario spec doesn't describe what we're implementing). "
            "This halts the scenario.\n"
            "  - 'code': the increment has a defect the next increment "
            "needs to be aware of (carry-forward).\n"
            "  - 'cosmetic': natural-language text only; doesn't affect "
            "executable behavior. Queued for the human-review cosmetic queue.\n\n"
            "Set the `route` field on each finding to one of those three "
            "values. The `suggestion` field is the actual text of the "
            "suggestion — do NOT embed a route prefix in it; the route "
            "lives on the structured field. InspectLoopStage reads "
            "`route` directly.\n\n"
            "Be specific. Cite file paths and line numbers. Findings without "
            "rationale are rejected."
        )

    async def run(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        *,
        increment_diff: str,
        new_test: str,
        scenario_steps: list[str],
        recent_journal_window: list[InspectJournalEntry],
    ) -> ReviewerVerdict:
        """Run the reviewer. Plan 4's InspectLoopStage (Task 12) calls this.

        Note: this is a single-increment LLM call (not a per-draft scenario call).
        The signature intentionally differs from `ReviewerAgent.run` (per-increment
        inputs, not per-draft). Suppresses `reportIncompatibleMethodOverride` —
        the override is intentionally not Liskov-substitutable.
        """
        # Construct prompt in-line (do not use ReviewerAgent.run's signature):
        from datetime import UTC, datetime

        # Format carry-forward section
        cf_section = (
            "\n".join(
                f"  - [{e.severity}/{e.route}] {e.location}: {e.issue} (rationale: {e.rationale})"
                for e in recent_journal_window
            )
            or "  (no carry-forward)"
        )

        prompt = (
            f"Increment diff:\n{increment_diff}\n\n"
            f"New test:\n{new_test}\n\n"
            f"Scenario steps:\n" + "\n".join(f"  {s}" for s in scenario_steps) + "\n\n"
            f"Recent carry-forward (from inspect journal):\n{cf_section}"
        )

        result = (await self._agent.run(prompt)).output
        # Force the dimension + timestamps (do not trust LLM output for these)
        result_dict = result.model_dump()
        result_dict["dimension"] = self.dimension
        result_dict["reviewed_at"] = datetime.now(UTC)
        result_dict["reviewer_id"] = f"{self.dimension}@v1"
        # Note: draft_hash is not meaningful at per-increment scope; use a stable placeholder
        result_dict["draft_hash"] = ""
        return ReviewerVerdict.model_validate(result_dict)
