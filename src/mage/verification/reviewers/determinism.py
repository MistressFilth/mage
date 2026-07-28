"""determinism reviewer — no I/O, time, randomness outside fixtures."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class DeterminismReviewer(ReviewerAgent):
    """Checks whether the scenario is deterministic and replayable.

    Rubric:
    - No unseeded randomness.
    - No wall-clock time dependencies (use injected clock).
    - No I/O outside fixtures (filesystem, network, DB).
    - Output is fully determined by inputs.
    """

    dimension = "determinism"

    def _system_prompt(self) -> str:
        return (
            "You are the determinism reviewer for HAILERIS v2.\n\n"
            "Evaluate whether the Given/When/Then scenario is deterministic and replayable.\n"
            "Check:\n"
            "1. No unseeded randomness (random.choice, random.random without seed).\n"
            "2. No wall-clock time dependencies (datetime.now() without injection).\n"
            "3. No I/O outside fixtures (filesystem, network, DB calls without setup).\n"
            "4. Output is fully determined by inputs.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
