"""RealizeStage: drives one increment of the inner TDD loop, with diff capture.

Plan 6: this stage is no longer a StageNode. It now rebuilds the
carry-forward and cross-scenario observations windows from the mapping's
inspect_journal before calling the agent (R3 / R21). It returns an
`IncrementResult` so `InspectLoopStage.inspect_increment` can hand the
diff to the reviewer without keyword-argument guesswork.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

from mage.agents.realize import RealizeAgent
from mage.artifacts.inspect import InspectJournalEntry
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
from mage.verification.host_overrides import HostConfig

CommandRunner = Callable[..., CompletedProcess[str]]

# Window sizes are host-configurable via HostConfig.per_scenario_window
# and HostConfig.cross_scenario_window (Spec R3 / R21).


def _default_command_runner(command: list[str], *, cwd: Path) -> CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class RealizeStage:
    """One increment: ask the agent to make the red test pass, then diff."""

    def __init__(
        self,
        events_log: EventsLog,
        agent: RealizeAgent,
        *,
        command_runner: CommandRunner | None = None,
        host_config: HostConfig,
    ) -> None:
        self.events_log = events_log
        self.agent = agent
        self.command_runner = command_runner or _default_command_runner
        self.host_config = host_config

    def _build_carry_forward(
        self, context: PipelineContext, sub_bid: str
    ) -> list[InspectJournalEntry]:
        """Build the per-scenario carry-forward window (R3 / R21).

        Pulls the last `host_config.per_scenario_window` entries from
        `mapping.inspect_journal[sub_bid]`.
        """
        window = self.host_config.per_scenario_window
        my_journal = context.mapping.inspect_journal.get(sub_bid, [])
        return [InspectJournalEntry.model_validate(e) for e in my_journal[-window:]]

    def _build_cross_scenario_observations(
        self, context: PipelineContext, sub_bid: str
    ) -> list[InspectJournalEntry]:
        """Build the cross-scenario observations window (R3 / R21).

        Takes the last `host_config.cross_scenario_window` entries from every OTHER
        sub_bid in `mapping.inspect_journal`, sorts by timestamp descending,
        and trims to `host_config.cross_scenario_window`.
        """
        window = self.host_config.cross_scenario_window
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
        """Run the agent, compute the diff, return an IncrementResult.

        Builds the per-scenario carry-forward and cross-scenario observations
        from the mapping's inspect_journal before invoking the agent. An
        optional `carry_forward` override is reserved for tests / Plan 7+8.
        """
        if carry_forward is None:
            carry_forward = self._build_carry_forward(context, target.sub_bid)
        cross_scenario = self._build_cross_scenario_observations(
            context, target.sub_bid
        )

        output = await self.agent.run(
            step=increment.step,
            scenario_context={"sub_bid": target.sub_bid},
            red_test_path=increment.red_test_path,
            carry_forward=carry_forward,
            cross_scenario_observations=cross_scenario,
        )
        diff = ""
        if output.files_changed:
            result = self.command_runner(
                ["git", "diff", "--unified=10", "--", *output.files_changed],
                cwd=context.project_dir,
            )
            diff = result.stdout
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
        return IncrementResult(
            files_changed=list(output.files_changed),
            summary=output.summary,
            diff=diff,
        )
