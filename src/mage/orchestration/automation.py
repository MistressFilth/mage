"""AutomationStage: graph-facing shim around FeatureRunner.

Reads approved scenarios from the mapping, builds ScenarioTargets, delegates
to FeatureRunner, and writes the resulting ScenarioOutcomes back to the
mapping. Emits SCENARIO_LIVE per completed scenario so InspectFeatureStage's
"all scenarios live" precondition is satisfied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mage.artifacts.mapping import LifecycleStatus, ScenarioEntry
from mage.orchestration.discipline.policy import guard_automation_entry
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.runner import FeatureRunner, ScenarioTarget


class AutomationStage(StageNode):
    """StageNode wrapping the automation loop."""

    name = "automation"

    def __init__(self, events_log: EventsLog, *, runner: FeatureRunner) -> None:
        super().__init__(events_log)
        self.runner = runner

    def _build_targets(self, context: PipelineContext) -> list[ScenarioTarget]:
        targets: list[ScenarioTarget] = []
        for entry in context.mapping.base_bids:
            for scenario in entry.scenarios:
                if scenario.lifecycle_status != LifecycleStatus.APPROVED:
                    continue
                guard_automation_entry(scenario)
                targets.append(
                    ScenarioTarget(
                        base_bid=entry.base_bid,
                        sub_bid=scenario.sub_bid,
                        scenario_name=scenario.sub_bid,
                        gherkin_body="",
                        steps=[],
                    )
                )
        return targets

    async def _run(self, context: PipelineContext) -> PipelineContext:
        targets = self._build_targets(context)
        outcomes = await self.runner.run(
            context, targets, cursor=context.automation_cursor
        )
        # Build a sub-bid -> outcome map for the write-back.
        outcomes_by_sub = {o.sub_bid: o for o in outcomes}

        new_base_bids = []
        for entry in context.mapping.base_bids:
            new_scenarios: list[ScenarioEntry] = []
            entry_changed = False
            for scenario in entry.scenarios:
                outcome = outcomes_by_sub.get(scenario.sub_bid)
                if outcome is None:
                    new_scenarios.append(scenario)
                    continue
                new_scenarios.append(
                    scenario.model_copy(
                        update={
                            "tests": list(scenario.tests) + list(outcome.test_paths),
                            "lifecycle_status": LifecycleStatus.LIVE,
                        }
                    )
                )
                entry_changed = True
                await self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.SCENARIO_LIVE,
                        payload={
                            "sub_bid": scenario.sub_bid,
                            "test_paths": list(outcome.test_paths),
                        },
                    )
                )
            if entry_changed:
                new_base_bids.append(
                    entry.model_copy(update={"scenarios": new_scenarios})
                )
            else:
                new_base_bids.append(entry)

        new_mapping = context.mapping.model_copy(update={"base_bids": new_base_bids})
        context.mapping = new_mapping

        mapping_path = context.project_dir / "mapping.yaml"
        if context.project_dir is not None and Path(context.project_dir).exists():
            await new_mapping.save(mapping_path)
        context.automation_cursor = None
        return context
