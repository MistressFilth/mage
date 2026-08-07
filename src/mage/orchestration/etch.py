"""EtchStage: produces red tests for a scenario, one per step.

Plan 6: this stage is no longer a StageNode. It no longer owns the loop
variable (`sub_bid`, `scenario_name`) — those arrive in a `ScenarioTarget`
built by `AutomationStage`. It emits its own domain events; `AutomationStage`
emits the coarse STAGE_STARTED / STAGE_COMPLETED around it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mage.agents.etch import EtchAgent, PydanticEtchAgent
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, ScenarioTarget
from mage.verification.host_overrides import HostConfig


class ScenarioInspectHalted(Exception):
    """Raised when InspectLoop routes a finding to spec/halts the run."""


class EtchStage:
    """One pass through the steps of a scenario, producing one Increment per step."""

    def __init__(
        self,
        events_log: EventsLog,
        agent: EtchAgent,
        *,
        host_config: HostConfig | None = None,
    ) -> None:
        self.events_log = events_log
        self.agent = agent
        self.host_config = host_config
        self._build_agent()

    def _build_agent(self) -> None:
        """(Re)build self.agent from host_config when needed.

        Plan 9: if `host_config.model` is set and no concrete agent was passed,
        construct `PydanticEtchAgent(model=host_config.model)`. Otherwise
        keep the stub that was injected (e.g. `_StubEtchAgent` in --dry-run).
        """
        if self.host_config is None or not self.host_config.model:
            return
        # Replace any stub with a real Pydantic-AI agent. Existing test setups
        # that inject their own agent AND host_config are unaffected because
        # the injection test sets `host_config.model=None`.
        if isinstance(self.agent, EtchAgent) and not isinstance(
            self.agent, PydanticEtchAgent
        ):
            self.agent = PydanticEtchAgent(model=self.host_config.model)

    async def run_scenario(
        self, context: PipelineContext, target: ScenarioTarget
    ) -> list[Increment]:
        """Generate a red test for each step. Returns increments in step order."""
        await self.events_log.append(
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
            spec = await self.agent.run(
                step=step,
                scenario_context={"sub_bid": target.sub_bid},
            )
            await self.events_log.append(
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
            await self.events_log.append(
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
        # P29: emit a final ETCH_COMPLETED after the loop closes, regardless
        # of whether any iterations ran. The empty-steps path no longer
        # leaves the audit trail dangling on ETCH_STARTED.
        red_test_count = len(target.steps)
        final_payload: dict = {
            "scenario_name": target.scenario_name,
            "red_test_count": red_test_count,
        }
        if red_test_count == 0:
            final_payload["reason"] = "no_steps"
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.ETCH_COMPLETED,
                payload=final_payload,
            )
        )
        return increments
