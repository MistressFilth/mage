"""Tests for FileStatePersistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from haileris_v2.orchestration.persistence import FileStatePersistence


class SampleState(BaseModel):
    """A simple state model for testing."""

    iteration: int = 0
    current_scenario: str | None = None
    notes: str = ""


class TestFileStatePersistence:
    def test_init_creates_dir(self, tmp_path: Path):
        state_dir = tmp_path / "state"
        FileStatePersistence(state_dir)
        assert state_dir.exists()

    def test_load_when_no_state(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        assert persistence.load_state(SampleState) is None

    def test_round_trip(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        state = SampleState(iteration=3, current_scenario="00000-A", notes="hello")
        persistence.save_state(state)
        loaded = persistence.load_state(SampleState)
        assert loaded is not None
        assert loaded.iteration == 3
        assert loaded.current_scenario == "00000-A"
        assert loaded.notes == "hello"

    def test_save_is_atomic(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        state = SampleState(iteration=1)
        persistence.save_state(state)
        # No temp files should remain.
        assert list((tmp_path / "state").glob("*.tmp")) == []

    def test_save_overwrites(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        persistence.save_state(SampleState(iteration=1))
        persistence.save_state(SampleState(iteration=2))
        loaded = persistence.load_state(SampleState)
        assert loaded is not None
        assert loaded.iteration == 2

    def test_recovers_from_corrupt_state(self, tmp_path: Path):
        # Write garbage to the state file; load should raise a clear error.
        persistence = FileStatePersistence(tmp_path / "state")
        state_file = tmp_path / "state" / "pipeline-state.yaml"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not: valid: yaml: at all: :::")
        with pytest.raises(Exception):  # Pydantic ValidationError or yaml.YAMLError
            persistence.load_state(SampleState)
