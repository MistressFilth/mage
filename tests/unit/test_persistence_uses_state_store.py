"""FileStatePersistence must read/write via StateStore (P32 task 11)."""

from __future__ import annotations

from pydantic import BaseModel

from mage.orchestration.persistence import FileStatePersistence
from mage.state_store import StateStore


class _StubState(BaseModel):
    stage: str = "inscribe"


def test_persistence_writes_via_state_store(state_store: StateStore) -> None:
    persistence = FileStatePersistence(state_store=state_store, state_type=_StubState)
    persistence.save_state(_StubState(stage="realize"))
    assert b"realize" in state_store.read("state/pipeline-state.yaml")


def test_persistence_loads_from_state_store(state_store: StateStore) -> None:
    state_store.write("state/pipeline-state.yaml", b"stage: etch\n")
    persistence = FileStatePersistence(state_store=state_store, state_type=_StubState)
    loaded = persistence.load_state()
    assert loaded is not None
    assert loaded.stage == "etch"
