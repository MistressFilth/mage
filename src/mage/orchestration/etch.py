"""Etch stage: orchestrates red-test generation for the inner TDD loop."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.agents.etch import EtchAgent
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode


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


class EtchStage(StageNode):
    """Runs once per scenario during the inner TDD cycle. Generates red tests for each step."""

    name = "etch"

    def __init__(self, events_log: EventsLog, agent: EtchAgent) -> None:
        super().__init__(events_log)
        self.agent = agent

    def _run(self, context: PipelineContext) -> PipelineContext:  # noqa: ARG002
        # Plan 4 stub: emits ETCH_STARTED + ETCH_COMPLETED + ETCH_RED_CONFIRMED per step.
        # Real scenario iteration happens via the RealizeStage loop (Task 11/12).
        # Test harness injects a StubAgent that returns RedTestSpec instances.
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.ETCH_STARTED,
                payload={"scenario_name": "stub", "increment_index": 0},
            )
        )
        # Two-step stub loop (test fixture only — see test_etch_stage.py)
        for step_idx in range(2):
            try:
                spec = self.agent.run(
                    step=f"step-{step_idx}",
                    scenario_context={"scenario_name": "stub"},
                )
            except NotImplementedError:
                # No real agent wired; emit completion event only. Real agent in
                # follow-up. Tests use StubAgent that bypasses NotImplementedError.
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.ETCH_COMPLETED,
                        payload={"scenario_name": "stub", "red_test_count": 0},
                    )
                )
                return context
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.ETCH_RED_CONFIRMED,
                    payload={
                        "step_name": spec.step_name,
                        "test_path": spec.test_path,
                        "increment_id": f"stub-{step_idx}",
                    },
                )
            )
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.ETCH_COMPLETED,
                payload={"scenario_name": "stub", "red_test_count": 2},
            )
        )
        return context
