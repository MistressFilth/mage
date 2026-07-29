"""InspectFeature stage: orchestrates end-of-feature Inspect + 3-tier severity routing."""

from __future__ import annotations


class InspectFeatureHalted(Exception):
    """Raised when end-of-feature iteration budget is exhausted.

    Resume re-enters InspectFeatureStage from the events log.
    """

    def __init__(self, feature_id: str, iteration: int) -> None:
        self.feature_id = feature_id
        self.iteration = iteration
        super().__init__(
            f"InspectFeatureHalted for feature {feature_id!r} at iteration {iteration} "
            f"(eof_max_iterations exceeded)"
        )
