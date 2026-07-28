"""Realize stage: makes red tests green + refactors, with carry-forward injection."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.agents.realize import RealizeAgent
from mage.artifacts.inspect import InspectJournalEntry
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode


class RealizeStage(StageNode):
    """Runs once per scenario during the inner TDD cycle. Carries the journal forward."""

    name = "realize"

    def __init__(self, events_log: EventsLog, agent: RealizeAgent) -> None:
        super().__init__(events_log)
        self.agent = agent

    def _run(self, context: PipelineContext) -> PipelineContext:
        # Plan 4 stub: emit REALIZE_STARTED + REALIZE_COMPLETED only.
        # The actual per-increment loop is in Task 12's InspectLoopStage;
        # RealizeStage's task here is to provide the carry-forward injection
        # API (see _run_single_increment).
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.REALIZE_STARTED,
                payload={"scenario_name": "stub"},
            )
        )
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.REALIZE_COMPLETED,
                payload={"scenario_name": "stub", "red_test_count": 0},
            )
        )
        return context

    def _run_single_increment(
        self,
        context: PipelineContext,
        *,
        sub_bid: str,
        step: str,
        red_test_path: str,
        per_scenario_window: int = 5,
        cross_scenario_window: int = 3,
    ) -> None:
        """One increment of Realize. Called by InspectLoopStage (Task 12).

        Pulls carry-forward from mapping.inspect_journal[sub_bid] (last
        per_scenario_window entries) and cross-scenario entries (last
        cross_scenario_window entries from other sub_bids). Passes them
        to the RealizeAgent.
        """
        mapping = context.mapping
        my_journal = mapping.inspect_journal.get(sub_bid, [])
        recent = [
            InspectJournalEntry.model_validate(e) for e in my_journal[-per_scenario_window:]
        ]
        # Cross-scenario: take recent entries from each OTHER sub_bid
        other_journals = []
        for other_sb, entries in mapping.inspect_journal.items():
            if other_sb == sub_bid:
                continue
            other_journals.extend(
                InspectJournalEntry.model_validate(e)
                for e in entries[-cross_scenario_window:]
            )
        # Sort by timestamp descending, take last N
        other_journals.sort(key=lambda e: e.timestamp, reverse=True)
        cross_scenario = other_journals[:cross_scenario_window]

        self.agent.run(
            step=step,
            scenario_context={"sub_bid": sub_bid},
            red_test_path=red_test_path,
            carry_forward=recent,
            cross_scenario_observations=cross_scenario,
        )
