"""EtchAgent: produces a red unit test for the next increment."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class RedTestSpec(BaseModel):
    """The next red test Etch produces for the inner TDD loop."""

    model_config = ConfigDict(frozen=True)

    step_name: str
    test_path: str
    test_code: str


class EtchAgent:
    """Stub agent interface. Pydantic-AI wiring is parallel to Plan 3's InscribeAgent.

    Plan 4 ships the interface; full LLM wiring is a follow-up (Plan 9).
    Stage consumes the interface via dependency injection.
    """

    def __init__(self, model=None) -> None:
        self._model = model

    async def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        """Produce a red test for `step`. Concrete impl comes from subclass or stub."""
        raise NotImplementedError(
            "EtchAgent.run() must be replaced with a concrete implementation "
            "or a stub for testing."
        )


_ETCH_SYSTEM_PROMPT = """You write ONE red (failing) pytest test for a BDD step.

Given `step` (the When/Then clause) and `scenario_context` (scenario name,
related tags, prior tests), produce a RedTestSpec dict with:
- step_name: the step string (pass through)
- test_path: a sensible path like tests/test_<scenario>.py
- test_code: a complete pytest function with `assert False` or equivalent

Test must fail before any production code is written.
"""


class PydanticEtchAgent(EtchAgent):
    """Concrete EtchAgent backed by Pydantic-AI."""

    def __init__(self, *, model: Any = None) -> None:
        super().__init__(model=model)
        from pydantic_ai import Agent

        self._agent: Agent[None, dict[str, Any]] = Agent(
            model=model or "test",
            deps_type=type(None),
            output_type=dict,
            system_prompt=_ETCH_SYSTEM_PROMPT,
        )

    async def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        prompt = f"step={step!r}\nscenario_context={scenario_context!r}"
        result = await self._agent.run(prompt)
        data = result.output
        return RedTestSpec(
            step_name=data.get("step_name", step),
            test_path=data["test_path"],
            test_code=data["test_code"],
        )
