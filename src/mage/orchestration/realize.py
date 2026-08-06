"""RealizeStage: drives one increment of the inner TDD loop, with diff capture.

Plan 6: this stage is no longer a StageNode. It rebuilds the
carry-forward and cross-scenario observations windows from the mapping's
inspect_journal before calling the agent (R3 / R21). It returns an
`IncrementResult` so `InspectLoopStage.inspect_increment` can hand the
diff to the reviewer without keyword-argument guesswork.

P27: diff capture is now increment-relative via `increment_diff`
(snapshot pre-agent, diff post-agent). The previous `git diff -- <paths>`
implementation was repository-relative — cumulative prior-increment edits,
omitted staged, empty for new untracked files — and is removed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mage.agents.realize import RealizeAgent
from mage.artifacts.inspect import InspectJournalEntry
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.increment_diff import compute_unified_diff, snapshot_tree
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
from mage.verification.host_overrides import HostConfig


class RealizeStage:
    """One increment: ask the agent to make the red test pass, then diff."""

    def __init__(
        self,
        events_log: EventsLog,
        agent: RealizeAgent,
        *,
        host_config: HostConfig,
    ) -> None:
        self.events_log = events_log
        self.agent = agent
        self.host_config = host_config

    def _build_carry_forward(
        self, context: PipelineContext, sub_bid: str
    ) -> list[InspectJournalEntry]:
        """Build the per-scenario carry-forward window (R3 / R21).

        Pulls the last `host_config.per_scenario_window` entries from
        `mapping.inspect_journal[sub_bid]`. Non-positive window sizes
        (0 or negative) produce an empty carry-forward: ``my_journal[-0:]``
        is the full list (Python treats ``-0`` as ``0``), so an explicit
        guard is required.
        """
        window = self.host_config.per_scenario_window
        if window <= 0:
            return []
        my_journal = context.mapping.inspect_journal.get(sub_bid, [])
        return [InspectJournalEntry.model_validate(e) for e in my_journal[-window:]]

    def _build_cross_scenario_observations(
        self, context: PipelineContext, sub_bid: str
    ) -> list[InspectJournalEntry]:
        """Build the cross-scenario observations window (R3 / R21).

        Takes the last `host_config.cross_scenario_window` entries from every OTHER
        sub_bid in `mapping.inspect_journal`, sorts by timestamp descending,
        and trims to `host_config.cross_scenario_window`. Non-positive window
        sizes produce an empty cross-scenario slice (see ``_build_carry_forward``
        for the rationale).
        """
        window = self.host_config.cross_scenario_window
        if window <= 0:
            return []
        other: list[InspectJournalEntry] = []
        for other_sb, entries in context.mapping.inspect_journal.items():
            if other_sb == sub_bid:
                continue
            other.extend(
                InspectJournalEntry.model_validate(e) for e in entries[-window:]
            )
        other.sort(key=lambda e: e.timestamp, reverse=True)
        return other[:window]

    async def run_increment(
        self,
        context: PipelineContext,
        *,
        target: ScenarioTarget,
        increment: Increment,
        carry_forward: list | None = None,
    ) -> IncrementResult:
        """Run the agent, compute the increment-relative diff, return result.

        Pre-agent: snapshot the project tree. Post-agent: compute the diff
        for `output.files_changed` against the snapshot. Emit
        `REALIZE_INCREMENT_DIFF_INCOMPLETE` when the diff builder reports
        warnings (path traversal, both-missing, read errors).
        """
        if carry_forward is None:
            carry_forward = self._build_carry_forward(context, target.sub_bid)
        cross_scenario = self._build_cross_scenario_observations(
            context, target.sub_bid
        )

        pre = snapshot_tree(context.project_dir)
        output = await self.agent.run(
            step=increment.step,
            scenario_context={"sub_bid": target.sub_bid},
            red_test_path=increment.red_test_path,
            carry_forward=carry_forward,
            cross_scenario_observations=cross_scenario,
        )
        diff, warnings = compute_unified_diff(
            context.project_dir, list(output.files_changed), pre
        )
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.REALIZE_INCREMENT_DONE,
                payload={
                    "sub_bid": target.sub_bid,
                    "step": increment.step,
                    "files_changed": output.files_changed,
                },
            )
        )
        if warnings:
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.REALIZE_INCREMENT_DIFF_INCOMPLETE,
                    payload={
                        "sub_bid": target.sub_bid,
                        "step": increment.step,
                        "warnings": warnings,
                    },
                )
            )
        return IncrementResult(
            files_changed=list(output.files_changed),
            summary=output.summary,
            diff=diff,
        )