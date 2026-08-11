"""EtchStage: produces red tests for a scenario, one per step.

Plan 6: this stage is no longer a StageNode. It no longer owns the loop
variable (`sub_bid`, `scenario_name`) — those arrive in a `ScenarioTarget`
built by `AutomationStage`. It emits its own domain events; `AutomationStage`
emits the coarse STAGE_STARTED / STAGE_COMPLETED around it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from mage.agents.etch import EtchAgent, PydanticEtchAgent
from mage.host_project_config import MageTomlConfig
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
        mage_toml: MageTomlConfig | None = None,
        providers: dict[str, Any] | None = None,
        default_provider: str = "anthropic",
    ) -> None:
        self.events_log = events_log
        self.agent = agent
        self.host_config = host_config
        self.mage_toml = mage_toml
        self.providers = providers or {}
        self.default_provider = default_provider
        self._build_agent()

    def _build_agent(self) -> None:
        """(Re)build self.agent from the resolved model when needed.

        P31: when a `mage_toml` is supplied and no concrete agent was passed,
        resolve the `etch` model through the provider chain and construct a
        `PydanticEtchAgent`. Otherwise keep the stub that was injected (e.g.
        `_StubEtchAgent` in --dry-run). No `events_log` is threaded here
        because `__init__` is synchronous and `EventsLog.append` is a
        coroutine; PROVIDER_RESOLVED for etch is emitted by the caller that
        builds the stage.
        """
        if self.mage_toml is None:
            return
        # Replace any stub with a real Pydantic-AI agent. Existing test setups
        # that inject their own agent pass no mage_toml, so they are unaffected.
        if isinstance(self.agent, EtchAgent) and not isinstance(
            self.agent, PydanticEtchAgent
        ):
            model, _, _ = self.mage_toml.model_for(
                "etch",
                providers=self.providers,
                default_provider=self.default_provider,
                env=dict(os.environ),
            )
            self.agent = PydanticEtchAgent(model=model)

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
