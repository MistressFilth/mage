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

    Plan 9 ships `PydanticEtchAgent` (concrete subclass below); the abstract
    base remains for test stubs and `--dry-run` mode. Stage consumes the
    interface via dependency injection.
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
    """Concrete EtchAgent backed by Pydantic-AI.

    Test mode (model is None or the string ``"test"``): bypasses the LLM
    entirely. The agent synthesizes a RedTestSpec directly from the
    ``step`` and ``scenario_context`` arguments. This makes E2E flows
    deterministic under ``model="test"`` without per-call TestModel
    configuration. Mirrors the CosmeticRefiner passthrough (Task 5).
    """

    def __init__(self, *, model: Any = None) -> None:
        super().__init__(model=model)
        self._is_test_mode = model is None or model == "test"
        if self._is_test_mode:
            # Skip Agent construction; run() builds RedTestSpec directly.
            self._agent: Agent[None, dict[str, Any]] | None = None
        else:
            from pydantic_ai import Agent

            self._agent = Agent(
                model=model,
                deps_type=type(None),
                output_type=dict,
                system_prompt=_ETCH_SYSTEM_PROMPT,
            )

    async def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        # Test-mode passthrough takes precedence; existing unit tests
        # inject a stub via self._agent, and that injection still wins.
        if self._is_test_mode and self._agent is None:
            scenario_name = (scenario_context or {}).get("scenario_name") or "scenario"
            slug = "".join(c if c.isalnum() else "_" for c in scenario_name).strip("_")
            func_name = "".join(c if c.isalnum() else "_" for c in step).strip("_")
            test_code = f"def test_{func_name or 'red'}():\n    assert False\n"
            return RedTestSpec(
                step_name=step,
                test_path=f"tests/test_{slug or 'red'}.py",
                test_code=test_code,
            )
        prompt = f"step={step!r}\nscenario_context={scenario_context!r}"
        result = await self._agent.run(prompt)  # ty: ignore[unresolved-attribute]
        data = result.output
        return RedTestSpec(
            step_name=data.get("step_name", step),
            test_path=data["test_path"],
            test_code=data["test_code"],
        )
