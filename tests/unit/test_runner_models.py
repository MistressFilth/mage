# tests/unit/test_runner_models.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mage.orchestration.runner import (
    AutomationCursor,
    Increment,
    IncrementResult,
    ScenarioOutcome,
    ScenarioTarget,
)


def test_scenario_target_is_frozen():
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy path",
        gherkin_body="Given x\nWhen y\nThen z",
        steps=["x", "y", "z"],
    )
    with pytest.raises(ValidationError):
        target.scenario_name = "other"


def test_increment_carries_red_test():
    inc = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="def test(): pass"
    )
    assert inc.index == 0
    with pytest.raises(ValidationError):
        inc.index = 1


def test_increment_result_requires_diff():
    # `diff` is a required field; constructing without it must raise ValidationError.
    with pytest.raises(ValidationError):
        IncrementResult.model_validate({"files_changed": ["a.py"], "summary": "ok"})


def test_scenario_outcome_holds_test_paths():
    out = ScenarioOutcome(sub_bid="00001-0001", test_paths=["t1.py", "t2.py"])
    assert out.test_paths == ["t1.py", "t2.py"]


def test_automation_cursor_defaults():
    cursor = AutomationCursor(sub_bid="00001-0001", increment_index=0, iteration=1)
    assert cursor.iteration == 1
    with pytest.raises(ValidationError):
        cursor.iteration = 2
