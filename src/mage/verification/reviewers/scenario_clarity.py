"""scenario_clarity reviewer — is the Given/When/Then readable and single-intent?"""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class ScenarioClarityReviewer(ReviewerAgent):
    """Checks whether the scenario is clearly written and single-intent.

    Rubric:
    - Each step is short and unambiguous.
    - Single intent: scenario tests one thing, not multiple.
    - No wandering prose; scenario is concise.
    - Pronouns ('it', 'they') have clear antecedents.
    """

    dimension = "scenario_clarity"

    def _system_prompt(self) -> str:
        return (
            "You are the scenario_clarity reviewer for HAILERIS v2.\n\n"
            "Evaluate the Given/When/Then scenario for clarity and single intent.\n"
            "Check:\n"
            "1. Each step is short, unambiguous, and free of pronouns with unclear antecedents.\n"
            "2. Single intent — scenario tests one thing, not multiple behaviors.\n"
            "3. No wandering prose; scenario is concise.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include "
            "findings with severity, location, issue, rationale (mandatory), suggestion."
        )
