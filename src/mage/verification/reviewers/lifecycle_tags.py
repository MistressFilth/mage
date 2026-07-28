"""lifecycle_tags reviewer — required status, sub-bid, cross-behavior tags present."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class LifecycleTagsReviewer(ReviewerAgent):
    """Checks whether required lifecycle tags are present and well-formed.

    Rubric:
    - @status tag present (one of: inscribing, approved, live, deprecated, retired).
    - @sub-bid tag present and matches Base85BID.derive(parent, index).
    - @cross-behavior-* tags present for each declared cross_behavior_link.
    - Tags are well-formed (no spaces, kebab-case).
    """

    dimension = "lifecycle_tags"

    def _system_prompt(self) -> str:
        return (
            "You are the lifecycle_tags reviewer for HAILERIS v2.\n\n"
            "Evaluate whether required lifecycle tags are present and well-formed.\n"
            "Check:\n"
            "1. @status tag present (inscribing/approved/live/deprecated/retired).\n"
            "2. @sub-bid tag present and well-formed (Base85-encoded).\n"
            "3. @cross-behavior-* tags present for each declared cross_behavior_link.\n"
            "4. Tags are well-formed: kebab-case, no spaces.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )