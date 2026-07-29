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