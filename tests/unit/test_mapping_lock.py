"""Tests for serialized async MappingArtifact saves."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


def _mapping(project_id: str = "p") -> MappingArtifact:
    return MappingArtifact(
        project_id=project_id,
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="behavior",
                behavior_description="description",
            )
        ],
    )


@pytest.mark.asyncio
async def test_concurrent_saves_serialize(tmp_path: Path):
    mapping = _mapping()
    paths = [tmp_path / f"mapping-{index}.yaml" for index in range(5)]

    coroutines = [mapping.save(path) for path in paths]
    await asyncio.gather(*coroutines)

    assert all(MappingArtifact.load(path).project_id == "p" for path in paths)
    assert mapping._get_save_lock() is mapping._get_save_lock()


@pytest.mark.asyncio
async def test_save_remains_atomic_for_readers(tmp_path: Path):
    path = tmp_path / "mapping.yaml"
    first = _mapping("first")
    second = _mapping("second")

    await first.save(path)
    assert MappingArtifact.load(path).project_id == "first"
    await second.save(path)
    assert MappingArtifact.load(path).project_id == "second"
