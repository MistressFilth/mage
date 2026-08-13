"""Mapping artifact save must go through StateStore (P32 task 10).

The pre-migration path was `MappingArtifact.save(path)` writing to
`<project_dir>/mapping.yaml`. After P32, the mapping lives on the
orphan branch and the canonical I/O is
`MappingArtifact.save_to_state_store(state_store)` /
`MappingArtifact.load_from_state_store(state_store)`. This module pins
that contract:

- `save_to_state_store` writes the artifact at the `mapping.yaml` path
  on the orphan branch; a subsequent read returns the same content.
- `load_from_state_store` returns a fresh empty artifact when the
  branch is absent (first run of a fresh project).
- The MAPPING_SAVED event still fires from `save_to_state_store` when
  an `events_log` is provided.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog, EventType
from mage.state_store import StateStore


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real git repo at ``tmp_path`` with identity configured (P32)."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _make_store(repo: Path) -> StateStore:
    """Build a real StateStore backed by real subprocess git."""
    return StateStore(repo, "feature-artifacts", identity=("T", "t@e"))


def test_load_from_state_store_returns_empty_when_branch_absent(git_repo: Path) -> None:
    """First-run contract: an absent orphan branch yields a fresh empty mapping."""
    store = _make_store(git_repo)
    # No write yet — ref doesn't exist. load_from_state_store must tolerate.
    loaded = MappingArtifact.load_from_state_store(store)

    assert loaded.project_id == git_repo.name
    assert loaded.base_bids == []
    assert loaded.cosmetic_findings == []


def test_save_to_state_store_writes_mapping_yaml_on_orphan_branch(
    git_repo: Path,
) -> None:
    """save_to_state_store persists at `mapping.yaml` on the orphan branch."""
    store = _make_store(git_repo)
    log = EventsLog(git_repo / "events.jsonl")
    mapping = MappingArtifact(
        project_id="demo",
        base_bids=[],
        feature_cosmetic_queue=[],
    )

    asyncio.run(mapping.save_to_state_store(store, events_log=log))

    loaded = MappingArtifact.load_from_state_store(store)
    assert loaded.project_id == "demo"

    # The MAPPING_SAVED event was emitted with the canonical payload.
    [event] = log.read_all()
    assert event.event_type == EventType.MAPPING_SAVED
    assert event.payload == {
        "feature_cosmetic_queue_size": 0,
        "base_bids_count": 0,
    }


def test_save_to_state_store_rejects_non_state_store() -> None:
    """The state_store arg is type-checked so a wrong arg fails loud, not silent."""
    mapping = MappingArtifact(project_id="x", base_bids=[])

    with pytest.raises(TypeError, match="state_store must be a StateStore"):
        asyncio.run(mapping.save_to_state_store("not-a-state-store"))  # type: ignore[arg-type]
