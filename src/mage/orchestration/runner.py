"""FeatureRunner: pure loop driver for the automation phase.

Owns the outer (per scenario) and inner (per increment) loops. Performs no
agent calls, emits no events, and writes no artifacts. Mutates only the
in-memory `PipelineContext.automation_cursor`. The graph-facing
`AutomationStage` (orchestration/automation.py) wraps the runner, applies
mapping writes, and emits lifecycle events.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ScenarioTarget(BaseModel):
    """One approved scenario, the unit of the outer loop."""

    model_config = ConfigDict(frozen=True)

    base_bid: str
    sub_bid: str
    scenario_name: str
    gherkin_body: str
    steps: list[str]


class Increment(BaseModel):
    """One red test Etch produced, the unit of the inner loop."""

    model_config = ConfigDict(frozen=True)

    index: int
    step: str
    red_test_path: str
    red_test_code: str


class IncrementResult(BaseModel):
    """What Realize produced for one increment."""

    model_config = ConfigDict(frozen=True)

    files_changed: list[str]
    summary: str
    diff: str


class ScenarioOutcome(BaseModel):
    """What AutomationStage writes back to the mapping per completed scenario."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    test_paths: list[str]


class AutomationCursor(BaseModel):
    """Position within the automation loop, persisted across halts."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    increment_index: int
    iteration: int


from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mage.orchestration.nodes import PipelineContext


class _EtchLike(Protocol):
    def run_scenario(self, context, target: ScenarioTarget) -> list[Increment]: ...


class _RealizeLike(Protocol):
    def run_increment(self, context, *, target, increment, carry_forward=None) -> IncrementResult: ...


class _InspectLike(Protocol):
    def inspect_increment(self, context, *, target, increment, result) -> "InspectRoute | None": ...


class FeatureRunner:
    """Owns the automation loops. No I/O, no events, no artifact writes."""

    def __init__(
        self,
        *,
        etch: _EtchLike,
        realize: _RealizeLike,
        inspect_loop: _InspectLike,
        per_loop_max_iterations: int,
    ) -> None:
        self.etch = etch
        self.realize = realize
        self.inspect_loop = inspect_loop
        self.per_loop_max_iterations = per_loop_max_iterations
        self.cursor: AutomationCursor | None = None

    def run(
        self,
        context: "PipelineContext",
        targets: list[ScenarioTarget],
    ) -> list[ScenarioOutcome]:
        outcomes: list[ScenarioOutcome] = []
        for target in targets:
            increments = self.etch.run_scenario(context, target)
            for increment in increments:
                iteration = 1
                while True:
                    self.cursor = AutomationCursor(
                        sub_bid=target.sub_bid,
                        increment_index=increment.index,
                        iteration=iteration,
                    )
                    context.automation_cursor = self.cursor
                    context.iteration = iteration
                    result = self.realize.run_increment(
                        context, target=target, increment=increment
                    )
                    route = self.inspect_loop.inspect_increment(
                        context, target=target, increment=increment, result=result
                    )
                    if route is None:
                        break
                    if route == "spec":
                        from mage.orchestration.etch import ScenarioInspectHalted

                        raise ScenarioInspectHalted(
                            f"spec-route finding for sub-bid {target.sub_bid!r} at iteration {iteration}"
                        )
                    if route == "code":
                        iteration += 1
                        if iteration > self.per_loop_max_iterations:
                            from mage.orchestration.etch import ScenarioInspectHalted

                            raise ScenarioInspectHalted(
                                f"per-loop budget exhausted for sub-bid {target.sub_bid!r}"
                            )
                        continue
                    # "cosmetic" — InspectLoopStage already queues and returns
                    # None, so this branch is unreachable in well-formed input.
                    break
            outcomes.append(
                ScenarioOutcome(
                    sub_bid=target.sub_bid,
                    test_paths=[inc.red_test_path for inc in increments],
                )
            )
            self.cursor = None
            context.automation_cursor = None
        return outcomes