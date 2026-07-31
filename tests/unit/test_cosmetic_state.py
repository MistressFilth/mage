from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.artifacts.cosmetic_state import (
    CosmeticApplied,
    CosmeticAppliedState,
    is_already_applied,
    load_state,
    save_state,
)


def _applied(**overrides):
    defaults = dict(
        content_hash="abc123",
        applied_at=datetime(2026, 7, 30, tzinfo=UTC),
        file=Path("src/example.py"),
        rationale="use a constant",
    )
    defaults.update(overrides)
    return CosmeticApplied(**defaults)


def test_cosmetic_state_load_returns_empty_when_missing(tmp_path):
    state = load_state(tmp_path)
    assert state.applied == {}


@pytest.mark.asyncio
async def test_cosmetic_state_save_then_load_round_trip(tmp_path):
    state = CosmeticAppliedState(applied={
        "00000-001": _applied(),
    })
    await save_state(tmp_path, state)
    loaded = load_state(tmp_path)
    assert loaded.applied["00000-001"].content_hash == "abc123"
    assert loaded.applied["00000-001"].file == Path("src/example.py")


def test_cosmetic_applied_serializes_via_pydantic():
    item = _applied()
    dumped = item.model_dump()
    reloaded = CosmeticApplied(**dumped)
    assert reloaded == item


def test_is_already_applied_returns_false_when_sub_bid_missing():
    state = CosmeticAppliedState()
    assert is_already_applied(state, "00000-001", "abc") is False


def test_is_already_applied_returns_true_when_hash_matches():
    state = CosmeticAppliedState(applied={"00000-001": _applied(content_hash="abc")})
    assert is_already_applied(state, "00000-001", "abc") is True


def test_is_already_applied_returns_false_when_hash_differs():
    state = CosmeticAppliedState(applied={"00000-001": _applied(content_hash="abc")})
    assert is_already_applied(state, "00000-001", "different") is False