"""Stage node base classes for the orchestration state machine."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.runner import AutomationCursor
from mage.verification.host_overrides import HostConfig


class PipelineContext(BaseModel):
    """Runtime context passed between stages."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_dir: Path
    mapping: MappingArtifact
    events_log: EventsLog
    current_stage: str | None = None
    current_sub_bid: str | None = None
    iteration: int = 0
    plan_path: Path | None = Field(default=None, validate_default=True)
    automation_cursor: AutomationCursor | None = None
    host_config: HostConfig | None = None
    feature_id: str = ""

    @field_serializer("events_log")
    def _serialize_events_log(self, log: EventsLog) -> str:
        """Serialize EventsLog by its log path so the context can persist."""
        return str(log.log_path)

    @field_validator("events_log", mode="before")
    @classmethod
    def _deserialize_events_log(cls, value: object) -> object:
        """Reconstruct EventsLog from a serialized path string on load."""
        if isinstance(value, str):
            return EventsLog(Path(value))
        return value

    @field_validator("plan_path", mode="before")
    @classmethod
    def _default_plan_path(cls, value: object, info) -> object:
        """Default plan_path to <project_dir>/plan.md if not provided."""
        if value is None:
            project_dir = info.data.get("project_dir")
            if project_dir is not None:
                return project_dir / "plan.md"
        return value

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        self._cycle_lock: asyncio.Lock | None = None  # lazy; requires running loop

    def _get_cycle_lock(self) -> asyncio.Lock:
        """Return the per-context asyncio.Lock, creating it lazily.

        Mirrors `EventsLog._get_lock` and `MappingArtifact._get_save_lock`.
        Lazy because `asyncio.Lock()` requires a running event loop.
        """
        if self._cycle_lock is None:
            self._cycle_lock = asyncio.Lock()
        return self._cycle_lock


class StageNode(ABC):
    """Abstract base for all pipeline stages.

    Subclasses must define `name` and implement async `_run()`. The base class
    emits STAGE_STARTED and STAGE_COMPLETED events around each run.
    """

    name: str = ""

    def __init__(self, events_log: EventsLog) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define `name`")
        self.events_log = events_log

    async def run(self, context: PipelineContext) -> PipelineContext:
        """Execute the stage, emitting start/complete events."""
        await self._emit(EventType.STAGE_STARTED)
        result = await self._run(context)
        await self._emit(EventType.STAGE_COMPLETED)
        return result

    @abstractmethod
    async def _run(self, context: PipelineContext) -> PipelineContext:
        """Stage-specific execution. Must be implemented by subclasses."""
        ...

    async def _emit(self, event_type: EventType, payload: dict | None = None) -> None:
        """Emit an event to the log."""
        event = Event(
            timestamp=datetime.now(UTC),
            event_type=event_type,
            payload={"stage": self.name, **(payload or {})},
        )
        await self.events_log.append(event)
