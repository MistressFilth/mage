"""FileStatePersistence: atomic state writes for the orchestration state machine."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class FileStatePersistence:
    """Persists a Pydantic state model to disk atomically.

    State files are written to <state_dir>/pipeline-state.yaml using a
    write-temp-then-rename pattern so partial writes never corrupt state.
    """

    def __init__(self, state_dir: Path, state_type: type[T]) -> None:
        self.state_dir = Path(state_dir)
        self.state_type = state_type
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "pipeline-state.yaml"

    def save_state(self, state: BaseModel) -> None:
        """Write state atomically (write-temp-then-rename)."""
        data = state.model_dump(mode="json")
        tmp_path = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp_path.write_text(yaml.safe_dump(data, sort_keys=False))
        tmp_path.replace(self.state_file)

    def load_state(self) -> T | None:
        """Load state, or return None if no state file exists.

        On corrupt state, quarantine the file and return None.
        """
        if not self.state_file.exists():
            return None
        try:
            data = yaml.safe_load(self.state_file.read_text())
            return self.state_type.model_validate(data)
        except (yaml.YAMLError, ValidationError):
            # Quarantine the corrupt file for diagnosis.
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            quarantine_path = self.state_file.with_name(
                f"{self.state_file.name}.corrupt.{timestamp}"
            )
            self.state_file.rename(quarantine_path)
            return None
