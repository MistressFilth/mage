"""RealizeAgent: makes red tests green + refactors.

Per spec R23 / GC-5: takes a carry_forward window of InspectJournalEntry
and injects a markdown summary into the prompt. Per spec R21: window size
defaults to 5 per-scenario + 3 cross-scenario; both host-configurable.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RealizeOutput(BaseModel):
    """The realization output: which files changed and a summary."""

    model_config = ConfigDict(frozen=True)

    files_changed: list[str]
    summary: str


class RealizeAgent:
    """Realize agent with carry-forward injection."""

    def __init__(self, model=None, *, system_prompt_only: bool = False) -> None:
        self._model = model
        self._system_prompt_only = system_prompt_only
        if not system_prompt_only:
            from pydantic_ai import Agent

            self._agent = Agent(model, output_type=RealizeOutput)

    def build_prompt(
        self,
        *,
        step: str,
        scenario_context: dict,
        red_test_path: str,
        carry_forward: list,  # list[InspectJournalEntry]
        cross_scenario_observations: list,  # list[InspectJournalEntry]
    ) -> str:
        """Build the full prompt with carry-forward injection.

        Public so tests can verify the injection shape. RealizeStage (Task 11)
        calls `run()` which internally calls build_prompt() + invokes the agent.
        """
        return self._build_prompt(
            step=step,
            scenario_context=scenario_context,
            red_test_path=red_test_path,
            carry_forward=carry_forward,
            cross_scenario_observations=cross_scenario_observations,
        )

    def _build_prompt(
        self,
        *,
        step: str,
        scenario_context: dict,
        red_test_path: str,
        carry_forward: list,
        cross_scenario_observations: list,
    ) -> str:
        cf_section = "\n".join(
            f"  - [{e.severity}/{e.route}] {e.location}: {e.issue} "
            f"(rationale: {e.rationale})"
            for e in carry_forward
        ) or "  (no carry-forward)"

        cs_section = "\n".join(
            f"  - [{e.severity}/{e.route}] {e.location}: {e.issue} "
            f"(rationale: {e.rationale})"
            for e in cross_scenario_observations
        ) or "  (none)"

        return (
            f"You are implementing the next increment of the inner TDD loop.\n\n"
            f"Step: {step}\n"
            f"Scenario context: {scenario_context}\n"
            f"Red test path: {red_test_path}\n\n"
            f"Recent carry-forward (per-scenario, from inspect journal):\n{cf_section}\n\n"
            f"Cross-scenario observations (other scenarios' recent journals):\n{cs_section}\n\n"
            f"Make the red test green. Refactor after green. "
            f"Do not modify the spec — only code + tests."
        )

    async def run(
        self,
        *,
        step: str,
        scenario_context: dict,
        red_test_path: str,
        carry_forward: list,
        cross_scenario_observations: list,
    ) -> RealizeOutput:
        """Run the agent. Plan 4 ships the interface; concrete LLM via Pydantic-AI follows."""
        if self._system_prompt_only:
            raise RuntimeError(
                "RealizeAgent constructed with system_prompt_only=True; run() is not callable"
            )
        prompt = self._build_prompt(
            step=step,
            scenario_context=scenario_context,
            red_test_path=red_test_path,
            carry_forward=carry_forward,
            cross_scenario_observations=cross_scenario_observations,
        )
        return (await self._agent.run(prompt)).output
