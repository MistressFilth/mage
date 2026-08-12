"""FileStatePersistence: state persistence via the orphan-branch StateStore."""

from __future__ import annotations

from datetime import UTC, datetime

import yaml
from pydantic import BaseModel, ValidationError

from mage.state_store import StateStore


class FileStatePersistence[T: BaseModel]:
    """Persists state to <orphan-branch>/state/pipeline-state.yaml."""

    STATE_PATH = "state/pipeline-state.yaml"

    def __init__(self, *, state_store: StateStore, state_type: type[T]) -> None:
        self.state_store = state_store
        self.state_type = state_type

    def save_state(self, state: BaseModel) -> None:
        data = yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False).encode(
            "utf-8"
        )
        self.state_store.write(self.STATE_PATH, data)

    def load_state(self) -> T | None:
        data = self.state_store.read(self.STATE_PATH)
        if not data:
            return None
        try:
            return self.state_type.model_validate(yaml.safe_load(data))
        except (yaml.YAMLError, ValidationError):
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            self.state_store.write(f"{self.STATE_PATH}.corrupt.{timestamp}", data)
            return None
