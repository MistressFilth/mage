"""Tests for FileStatePersistence."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from mage.orchestration.persistence import FileStatePersistence


class SampleState(BaseModel):
    """A simple state model for testing."""

    iteration: int = 0
    current_scenario: str | None = None
    notes: str = ""


class TestFileStatePersistence:
    def test_init_creates_dir(self, tmp_path: Path):
        state_dir = tmp_path / "state"
        FileStatePersistence(state_dir, SampleState)
        assert state_dir.exists()

    def test_load_when_no_state(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state", SampleState)
        assert persistence.load_state() is None

    def test_round_trip(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state", SampleState)
        state = SampleState(iteration=3, current_scenario="00000-A", notes="hello")
        persistence.save_state(state)
        loaded = persistence.load_state()
        assert loaded is not None
        assert loaded.iteration == 3
        assert loaded.current_scenario == "00000-A"
        assert loaded.notes == "hello"

    def test_save_is_atomic(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state", SampleState)
        state = SampleState(iteration=1)
        persistence.save_state(state)
        # No temp files should remain.
        assert list((tmp_path / "state").glob("*.tmp")) == []

    def test_save_overwrites(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state", SampleState)
        persistence.save_state(SampleState(iteration=1))
        persistence.save_state(SampleState(iteration=2))
        loaded = persistence.load_state()
        assert loaded is not None
        assert loaded.iteration == 2

    def test_recovers_from_corrupt_state_by_quarantining(self, tmp_path: Path):
        """Corrupt state file is quarantined and load returns None."""
        persistence = FileStatePersistence(tmp_path / "state", SampleState)
        state_file = tmp_path / "state" / "pipeline-state.yaml"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not: valid: yaml: at all: :::")
        # Recovery: load returns None, file is quarantined
        result = persistence.load_state()
        assert result is None
        # Original file no longer at expected location
        assert not state_file.exists()
        # Quarantined file exists
        quarantined = list((tmp_path / "state").glob("pipeline-state.yaml.corrupt.*"))
        assert len(quarantined) == 1

    def test_pipeline_context_round_trip_through_persistence(self, tmp_path: Path):
        """PipelineContext with EventsLog survives FileStatePersistence round-trip."""
        from mage.artifacts.mapping import MappingArtifact
        from mage.orchestration.events import EventsLog
        from mage.orchestration.nodes import PipelineContext

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(schema_version=2, project_id="rt", base_bids=[]),
            events_log=log,
            iteration=42,
            current_stage="test_stage",
        )
        persistence = FileStatePersistence(tmp_path / "state", PipelineContext)
        persistence.save_state(ctx)
        restored = persistence.load_state()
        assert restored is not None
        assert restored.iteration == 42
        assert restored.current_stage == "test_stage"
        # EventsLog survives via the path-based serializer/validator pair
        assert restored.events_log.log_path == log.log_path
