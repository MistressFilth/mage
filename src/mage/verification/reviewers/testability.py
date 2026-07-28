"""testability reviewer — can the scenario become a red/green unit test?"""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class TestabilityReviewer(ReviewerAgent):
    """Checks whether the scenario can be implemented as a unit test.

    Rubric:
    - Each step is observable (has a clear assertion target).
    - No hidden coupling (assertions don't depend on undocumented state).
    - Steps can be implemented as function calls or method invocations.
    - Failure modes are explicit.
    """

    dimension = "testability"

    def _system_prompt(self) -> str:
        return (
            "You are the testability reviewer for HAILERIS v2.\n\n"
            "Evaluate whether the Given/When/Then scenario can be implemented as "
            "a red/green unit test.\n"
            "Check:\n"
            "1. Each step is observable — has a clear assertion target.\n"
            "2. No hidden coupling — assertions don't depend on undocumented state.\n"
            "3. Steps can be implemented as function calls or method invocations.\n"
            "4. Failure modes are explicit (you can tell when the scenario fails).\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
