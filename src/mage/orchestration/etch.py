"""EtchStage: produces red tests for a scenario, one per step.

Plan 6: this stage is no longer a StageNode. It no longer owns the loop
variable (`sub_bid`, `scenario_name`) — those arrive in a `ScenarioTarget`
built by `AutomationStage`. It emits its own domain events; `AutomationStage`
emits the coarse STAGE_STARTED / STAGE_COMPLETED around it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mage.agents.etch import EtchAgent
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, ScenarioTarget


class ScenarioInspectHalted(Exception):
    """Raised when InspectLoop routes a finding to spec/halts the run."""


class EtchStage:
    """One pass through the steps of a scenario, producing one Increment per step."""

    def __init__(self, events_log: EventsLog, agent: EtchAgent) -> None:
        self.events_log = events_log
        self.agent = agent

    def run_scenario(
        self, context: PipelineContext, target: ScenarioTarget
    ) -> list[Increment]:
        """Generate a red test for each step. Returns increments in step order."""
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.ETCH_STARTED,
                payload={
                    "scenario_name": target.scenario_name,
                    "sub_bid": target.sub_bid,
                },
            )
        )
        increments: list[Increment] = []
        for index, step in enumerate(target.steps):
            spec = self.agent.run(
                step=step,
                scenario_context={"sub_bid": target.sub_bid},
            )
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.ETCH_RED_CONFIRMED,
                    payload={
                        "scenario_name": target.scenario_name,
                        "step_name": spec.step_name,
                        "red_test_path": spec.test_path,
                    },
                )
            )
            increments.append(
                Increment(
                    index=index,
                    step=spec.step_name,
                    red_test_path=spec.test_path,
                    red_test_code=spec.test_code,
                )
            )
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.ETCH_COMPLETED,
                    payload={
                        "scenario_name": target.scenario_name,
                        "step_name": spec.step_name,
                        "red_test_count": index + 1,
                    },
                )
            )
        return increments
