"""RealizeStage: drives one increment of the inner TDD loop, with diff capture.

Plan 6: this stage is no longer a StageNode. It no longer pulls
carry-forward from the mapping itself (FeatureRunner passes it), and it now
returns an `IncrementResult` so `InspectLoopStage.inspect_increment` can
hand the diff to the reviewer without keyword-argument guesswork.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

from mage.agents.realize import RealizeAgent
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget

CommandRunner = Callable[..., CompletedProcess[str]]


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
    ) -> None:
        self.events_log = events_log
        self.agent = agent
        self.command_runner = command_runner or _default_command_runner

    def run_increment(
        self,
        context: PipelineContext,
        *,
        target: ScenarioTarget,
        increment: Increment,
        carry_forward: list | None = None,
    ) -> IncrementResult:
        """Run the agent, compute the diff, return an IncrementResult.

        `carry_forward` is unused on the runner side; the journal-windowing
        logic that previously lived here moved to FeatureRunner so the runner
        owns its carry-forward policy. The parameter is kept for a future
        Plan 7/8 where the carry-forward may need override at the call site.
        """
        output = self.agent.run(
            step=increment.step,
            scenario_context={"sub_bid": target.sub_bid},
            red_test_path=increment.red_test_path,
            carry_forward=carry_forward or [],
            cross_scenario_observations=[],
        )
        diff = ""
        if output.files_changed:
            result = self.command_runner(
                ["git", "diff", "--unified=10", "--", *output.files_changed],
                cwd=context.project_dir,
            )
            diff = result.stdout
        self.events_log.append(
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
