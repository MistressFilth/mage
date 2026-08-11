"""EtchStage: produces red tests for a scenario, one per step.

Plan 6: this stage is no longer a StageNode. It no longer owns the loop
variable (`sub_bid`, `scenario_name`) — those arrive in a `ScenarioTarget`
built by `AutomationStage`. It emits its own domain events; `AutomationStage`
emits the coarse STAGE_STARTED / STAGE_COMPLETED around it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
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
        # ``_build_agent`` collects any PROVIDER_RESOLVED /
        # PROVIDER_RESOLVED_FAILED events synchronously; they need to be
        # awaited against the real async EventsLog before any audit-trail
        # reader sees the run. ``FeatureRunner.run`` calls
        # ``flush_pending_events`` before the first scenario loop iteration.
        self._pending_provider_events: list[Event] = []
        self._build_agent()

    def _build_agent(self) -> None:
        """(Re)build self.agent from the resolved model when needed.

        P31: when a ``mage_toml`` is supplied and no concrete agent was
        passed, resolve the ``etch`` model through the provider chain and
        construct a ``PydanticEtchAgent``. ``model_for`` appends
        ``PROVIDER_RESOLVED`` synchronously to ``self.events_log``, which
        would build a coroutine nobody awaits and silently drop the event;
        route the appends into a sync sink (collected on
        ``self._pending_provider_events``) so the caller can flush them via
        :meth:`flush_pending_events` once it has a running event loop.
        """
        if self.mage_toml is None:
            return
        # Replace any stub with a real Pydantic-AI agent. Existing test setups
        # that inject their own agent pass no mage_toml, so they are unaffected.
        if isinstance(self.agent, EtchAgent) and not isinstance(
            self.agent, PydanticEtchAgent
        ):
            sink: Any = SimpleNamespace(append=self._pending_provider_events.append)
            model, _, _ = self.mage_toml.model_for(
                "etch",
                providers=self.providers,
                default_provider=self.default_provider,
                env=dict(os.environ),
                events_log=sink,
            )
            self.agent = PydanticEtchAgent(model=model)

    async def flush_pending_events(self) -> None:
        """Await each collected PROVIDER_RESOLVED[_FAILED] event against
        ``self.events_log``.

        Idempotent: drained buffer is replaced with an empty list after the
        flush so a second call is a no-op.
        """
        pending = self._pending_provider_events
        self._pending_provider_events = []
        for event in pending:
            await self.events_log.append(event)

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
