"""FileStatePersistence must read/write via StateStore (P32 task 11)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from mage.orchestration.persistence import FileStatePersistence
from mage.state_store import StateStore


class _StubState(BaseModel):
    stage: str = "inscribe"


@pytest.fixture
def git_store(tmp_path: Path) -> StateStore:
    """StateStore backed by a real git repo in tmp_path (P32)."""
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
    return StateStore(tmp_path, "feature-artifacts", identity=("T", "t@e"))


def test_persistence_writes_via_state_store(git_store: StateStore) -> None:
    persistence = FileStatePersistence(state_store=git_store, state_type=_StubState)
    persistence.save_state(_StubState(stage="realize"))
    assert b"realize" in git_store.read("state/pipeline-state.yaml")


def test_persistence_loads_from_state_store(git_store: StateStore) -> None:
    git_store.write("state/pipeline-state.yaml", b"stage: etch\n")
    persistence = FileStatePersistence(state_store=git_store, state_type=_StubState)
    loaded = persistence.load_state()
    assert loaded is not None
    assert loaded.stage == "etch"
