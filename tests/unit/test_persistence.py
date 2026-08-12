"""Tests for FileStatePersistence (orphan-branch StateStore)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from mage.orchestration.persistence import FileStatePersistence
from mage.state_store import StateStore


class SampleState(BaseModel):
    """A simple state model for testing."""

    iteration: int = 0
    current_scenario: str | None = None
    notes: str = ""


class TestFileStatePersistence:
    def test_init_accepts_state_store(self, state_store: StateStore):
        FileStatePersistence(state_store=state_store, state_type=SampleState)

    def test_load_when_no_state(self, state_store: StateStore):
        persistence = FileStatePersistence(
            state_store=state_store, state_type=SampleState
        )
        assert persistence.load_state() is None

    def test_round_trip(self, state_store: StateStore):
        persistence = FileStatePersistence(
            state_store=state_store, state_type=SampleState
        )
        state = SampleState(iteration=3, current_scenario="00000-A", notes="hello")
        persistence.save_state(state)
        loaded = persistence.load_state()
        assert loaded is not None
        assert loaded.iteration == 3
        assert loaded.current_scenario == "00000-A"
        assert loaded.notes == "hello"

    def test_save_overwrites(self, state_store: StateStore):
        persistence = FileStatePersistence(
            state_store=state_store, state_type=SampleState
        )
        persistence.save_state(SampleState(iteration=1))
        persistence.save_state(SampleState(iteration=2))
        loaded = persistence.load_state()
        assert loaded is not None
        assert loaded.iteration == 2

    def test_recovers_from_corrupt_state_by_quarantining(
        self, state_store: StateStore
    ):
        """Corrupt state file is quarantined and load returns None."""
        state_store.write(FileStatePersistence.STATE_PATH, b"not: valid: yaml: at all: :::")
        persistence = FileStatePersistence(
            state_store=state_store, state_type=SampleState
        )
        result = persistence.load_state()
        assert result is None
        assert state_store.read(FileStatePersistence.STATE_PATH) == b""
        ls = subprocess.run(
            ["git", "ls-tree", "-r", state_store.full_ref, "--", "state/"],
            cwd=state_store.project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        quarantined = [
            line
            for line in ls.stdout.splitlines()
            if "pipeline-state.yaml.corrupt." in line
        ]
        assert len(quarantined) == 1

    def test_pipeline_context_round_trip_through_persistence(
        self, tmp_path: Path, state_store: StateStore
    ):
        """PipelineContext with EventsLog survives FileStatePersistence round-trip."""
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import EventsLog
        from mage.orchestration.nodes import PipelineContext

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            state_store=state_store,
            project_dir=tmp_path,
            mapping=MappingArtifact(schema_version=2, project_id="rt", base_bids=[]),
            events_log=log,
            iteration=42,
            current_stage="test_stage",
        )
        persistence = FileStatePersistence(
            state_store=state_store, state_type=PipelineContext
        )
        persistence.save_state(ctx)
        restored = persistence.load_state()
        assert restored is not None
        assert restored.iteration == 42
        assert restored.current_stage == "test_stage"
        assert restored.events_log.log_path == log.log_path
