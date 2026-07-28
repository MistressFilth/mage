"""Etch stage: orchestrates red-test generation for the inner TDD loop."""

from __future__ import annotations


class ScenarioInspectHalted(Exception):
    """Raised when per-loop iteration budget is exhausted OR a spec-route finding halts.

    Feature continues with other scenarios; halted scenario's state is on disk
    via inspect_journal and MappingArtifact.feature_status.
    """

    def __init__(
        self, base_bid: str, scenario_name: str, sub_bid: str, iteration: int
    ) -> None:
        self.base_bid = base_bid
        self.scenario_name = scenario_name
        self.sub_bid = sub_bid
        self.iteration = iteration
        super().__init__(
            f"Scenario {scenario_name!r} (sub_bid={sub_bid!r}) halted at "
            f"iteration {iteration} (budget exhausted or spec-route halt)"
        )
