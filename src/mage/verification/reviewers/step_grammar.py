"""step_grammar reviewer — declarative phrasing, no imperative leakage."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class StepGrammarReviewer(ReviewerAgent):
    """Checks whether steps use declarative phrasing.

    Rubric:
    - Steps use 3rd-person present tense, not imperative ("click", "type").
    - Steps reuse defined steps where applicable.
    - No UI-control language (click, drag, hover) in non-UI scenarios.
    """

    dimension = "step_grammar"

    def _system_prompt(self) -> str:
        return (
            "You are the step_grammar reviewer for HAILERIS v2.\n\n"
            "Evaluate the Given/When/Then steps for declarative phrasing.\n"
            "Check:\n"
            "1. No imperative verbs (click, type, drag, hover) unless the scenario "
            "   is explicitly UI-driven.\n"
            "2. Steps are written in 3rd-person present tense.\n"
            "3. Steps reuse defined step patterns where applicable.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )