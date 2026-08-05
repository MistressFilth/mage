"""Idempotency state for `mage cosmetic apply` re-runs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_STATE_FILENAME = "cosmetic_applied.yaml"
_STATE_DIR = ".mage"


class CosmeticApplied(BaseModel):
    """Record of one successful cosmetic apply. Frozen + digest-pinned."""

    model_config = ConfigDict(frozen=True)

    content_hash: str
    file: Path
    rationale: str


class CosmeticAppliedState(BaseModel):
    """All applied cosmetic items keyed by sub_bid."""

    applied: dict[str, CosmeticApplied] = Field(default_factory=dict)


def _state_path(project_dir: Path) -> Path:
    return project_dir / _STATE_DIR / _STATE_FILENAME


_GLOBAL_LOCKS: dict[str, asyncio.Lock] = {}


def _get_lock(project_dir: Path) -> asyncio.Lock:
    """Return a per-instance asyncio.Lock, lazily created (Plan 8 pattern)."""
    key = str(project_dir.resolve())
    if key not in _GLOBAL_LOCKS:
        _GLOBAL_LOCKS[key] = asyncio.Lock()
    return _GLOBAL_LOCKS[key]


def load_state(project_dir: Path) -> CosmeticAppliedState:
    """Load idempotency state. Returns empty on missing/corrupt (fail-open)."""
    path = _state_path(project_dir)
    if not path.exists():
        return CosmeticAppliedState()
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return CosmeticAppliedState(**data)
    except (yaml.YAMLError, OSError, ValidationError, TypeError):
        return CosmeticAppliedState()


async def save_state(project_dir: Path, state: CosmeticAppliedState) -> None:
    """Atomic write via temp + rename. Holds the per-project asyncio.Lock."""
    target = _state_path(project_dir)
    async with _get_lock(project_dir):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(state.model_dump(mode="json")))
        tmp.replace(target)


def is_already_applied(
    state: CosmeticAppliedState, sub_bid: str, content_hash: str
) -> bool:
    """True iff this sub_bid was previously applied with the same content."""
    record = state.applied.get(sub_bid)
    return record is not None and record.content_hash == content_hash
