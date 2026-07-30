"""EtchAgent: produces a red unit test for the next increment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RedTestSpec(BaseModel):
    """The next red test Etch produces for the inner TDD loop."""

    model_config = ConfigDict(frozen=True)

    step_name: str
    test_path: str
    test_code: str


class EtchAgent:
    """Stub agent interface. Pydantic-AI wiring is parallel to Plan 3's InscribeAgent.

    Plan 4 ships the interface; full LLM wiring is a follow-up (Plan 6 territory).
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
