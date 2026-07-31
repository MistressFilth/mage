"""naming_idiom reviewer — scenario names + tags follow host conventions."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class NamingIdiomReviewer(ReviewerAgent):
    """Checks whether scenario names and tags follow host conventions.

    Rubric:
    - Scenario name uses kebab-case or snake_case (project-defined).
    - Tag names use kebab-case.
    - Tag vocabulary matches existing tags (no made-up domains).
    - Scenario name is concise and descriptive.
    """

    dimension = "naming_idiom"

    def _system_prompt(self) -> str:
        return (
            "You are the naming_idiom reviewer for mage.\n\n"
            "Evaluate whether scenario names and tags follow host project conventions.\n"
            "Check:\n"
            "1. Scenario name uses kebab-case or snake_case as appropriate.\n"
            "2. Tag names use kebab-case.\n"
            "3. Tag vocabulary matches existing registered tags (no made-up domains).\n"
            "4. Scenario name is concise (5-10 words) and descriptive.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
