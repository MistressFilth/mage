"""Unit tests for the StageHalted exception."""

from __future__ import annotations

import pytest

from mage.orchestration.exceptions import StageHalted


def test_stage_halted_carries_required_fields():
    exc = StageHalted(
        reason="plan_approval",
        originating_stage="decomposition",
        affected_behaviors=["auth"],
        feature_id="feat-001",
        plan_digest="abc123",
    )
    assert exc.reason == "plan_approval"
    assert exc.originating_stage == "decomposition"
    assert exc.affected_behaviors == ["auth"]
    assert exc.context == {"feature_id": "feat-001", "plan_digest": "abc123"}
    assert str(exc) == "plan_approval"


def test_stage_halted_defaults():
    exc = StageHalted(reason="plan_approval")
    assert exc.originating_stage == "decomposition"
    assert exc.affected_behaviors == []
    assert exc.context == {}


def test_stage_halted_is_an_exception():
    with pytest.raises(StageHalted) as exc_info:
        raise StageHalted(reason="plan_approval")
    assert exc_info.value.reason == "plan_approval"
