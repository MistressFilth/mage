"""spec_compliance reviewer — does the scenario implement the behavior spec?"""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class SpecComplianceReviewer(ReviewerAgent):
    """Checks whether the drafted scenario implements the parent behavior spec.

    Rubric:
    - Scenario's `gherkin_body` should cover the behavior's description.
    - `depends_on` should be honored (no scenario implementing behavior X
      before behavior Y when X depends_on Y).
    - `cross_behavior_links` should be reflected in tags or step bodies.
    """

    dimension = "spec_compliance"

    def _system_prompt(self) -> str:
        return (
            "You are the spec_compliance reviewer for mage.\n\n"
            "Evaluate whether the drafted scenario implements the parent behavior spec.\n"
            "Check:\n"
            "1. The Given/When/Then covers the behavior's description.\n"
            "2. depends_on is honored (scenario doesn't implement a behavior "
            "   before its dependencies).\n"
            "3. cross_behavior_links are referenced via tags or step bodies.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include "
            "findings with severity (critical/major/minor), location, issue, "
            "rationale (mandatory), and suggestion."
        )
