"""Project-level mapping artifact: single source of truth for BIDs."""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mage.artifacts.bid import Base85BID, next_base_bid

if TYPE_CHECKING:
    from mage.artifacts.inspect import (
        CosmeticItem,
        InspectArtifactRef,
        InspectJournalEntry,
    )
    from mage.orchestration.events import EventsLog


class LifecycleStatus(str, Enum):
    INSCRIBING = "inscribing"
    APPROVED = "approved"
    LIVE = "live"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class BaseBIDNotFoundError(Exception):
    """Raised when an operation references a base_bid not in the mapping."""


class ReversionLogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_bid: str
    timestamp: datetime
    reason: str
    originating_stage: str


class PostLiveRevisionEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_bid: str
    timestamp: datetime
    human_approver: str
    before_hash: str
    after_hash: str


class ScenarioEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_bid: str
    scenario_text_hash: str
    lifecycle_status: LifecycleStatus
    supersedes: str | None = None
    superseded_by: str | None = None
    feature_id: str | None = None  # Plan 14: optional, legacy default=None
    tests: list[str] = Field(default_factory=list)
    derivations: list[str] = Field(default_factory=list)


class BaseBIDEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    base_bid: str
    behavior_name: str
    behavior_description: str
    depends_on: list[str] = Field(default_factory=list)
    notes: str = ""
    scenarios: list[ScenarioEntry] = Field(default_factory=list)
    reversion_log: list[ReversionLogEntry] = Field(default_factory=list)
    post_live_revisions: list[PostLiveRevisionEntry] = Field(default_factory=list)
    cross_behavior_links: list[str] = Field(default_factory=list)


class MappingArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: int = 2
    project_id: str
    base_bids: list[BaseBIDEntry] = Field(default_factory=list)

    # Plan 4 — Inner TDD loop + feature lifecycle state
    inspect_journal: dict[str, list[dict]] = Field(default_factory=dict)
    # ^ sub_bid (str) -> list[InspectJournalEntry] (kept as dict[str, list[dict]] to avoid circular import; see Tasks 6 + 11 for typed helpers)
    feature_inspect: dict | None = (
        None  # InspectArtifactRef; typing loose to avoid circular import
    )
    feature_cosmetic_queue: list[dict] = Field(default_factory=list)
    # ^ list[CosmeticItem]; typing loose to avoid circular import
    feature_status: str = "pending"  # pending | live_assembling | inspect_pending | inspect_passed | settled | halted

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        self._save_lock: asyncio.Lock | None = None  # lazy; requires running loop

    def _get_save_lock(self) -> asyncio.Lock:
        """Return the per-instance asyncio.Lock, creating it lazily.

        See `EventsLog._get_lock` for rationale. The lazy pattern avoids
        constructing the lock during `__init__` because `asyncio.Lock()`
        requires a running event loop.
        """
        if self._save_lock is None:
            self._save_lock = asyncio.Lock()
        return self._save_lock

    @model_validator(mode="after")
    def _validate_plan4_fields(self) -> MappingArtifact:
        """Defensive validation for Plan 4 fields whose types are kept loose
        (dict / list[dict]) to avoid circular imports.

        Important 5 fix: validate that
        - inspect_journal keys are non-empty strings and values are lists of dicts
        - feature_cosmetic_queue items are dicts
        - feature_inspect is None or a dict (and has expected shape)

        Failures surface here (on load / save) instead of as cryptic errors
        in downstream consumers.
        """
        # Validate inspect_journal.
        if not isinstance(self.inspect_journal, dict):
            raise ValueError(
                f"MappingArtifact.inspect_journal must be a dict; "
                f"got {type(self.inspect_journal).__name__}"
            )
        for k, v in self.inspect_journal.items():
            if not isinstance(k, str) or not k:
                raise ValueError(
                    f"MappingArtifact.inspect_journal keys must be non-empty "
                    f"strings; got {k!r}"
                )
            if not isinstance(v, list):
                raise ValueError(
                    f"MappingArtifact.inspect_journal[{k!r}] must be a list; "
                    f"got {type(v).__name__}"
                )
            for i, entry in enumerate(v):
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"MappingArtifact.inspect_journal[{k!r}][{i}] must be "
                        f"a dict; got {type(entry).__name__}"
                    )
        # Validate feature_cosmetic_queue.
        if not isinstance(self.feature_cosmetic_queue, list):
            raise ValueError(
                f"MappingArtifact.feature_cosmetic_queue must be a list; "
                f"got {type(self.feature_cosmetic_queue).__name__}"
            )
        for i, item in enumerate(self.feature_cosmetic_queue):
            if not isinstance(item, dict):
                raise ValueError(
                    f"MappingArtifact.feature_cosmetic_queue[{i}] must be a "
                    f"dict; got {type(item).__name__}"
                )
            feature_id = item.get("feature_id")
            if not isinstance(feature_id, str):
                raise ValueError(
                    f"MappingArtifact.feature_cosmetic_queue[{i}] must have a string "
                    f"'feature_id' field (empty string allowed; Plan 13 default); got {feature_id!r}"
                )
        # Validate feature_inspect (None or a dict).
        if self.feature_inspect is not None and not isinstance(
            self.feature_inspect, dict
        ):
            raise ValueError(
                f"MappingArtifact.feature_inspect must be None or a dict; "
                f"got {type(self.feature_inspect).__name__}"
            )
        return self

    def highest_base_bid(self) -> Base85BID | None:
        if not self.base_bids:
            return None
        return Base85BID(value=max(self.base_bids, key=lambda e: e.base_bid).base_bid)

    def next_base_bid(self) -> Base85BID:
        """Derive the next available base BID."""
        return next_base_bid(highest=self.highest_base_bid())

    def lookup_sub_bid(self, base: Base85BID, sub: str) -> ScenarioEntry | None:
        for entry in self.base_bids:
            if entry.base_bid == base.value:
                for scenario in entry.scenarios:
                    if scenario.sub_bid == sub:
                        return scenario
        return None

    def append_scenario(
        self, base_bid: str, scenario: ScenarioEntry
    ) -> MappingArtifact:
        """Return a new MappingArtifact with `scenario` appended to the matching BaseBIDEntry.scenarios.

        Raises BaseBIDNotFoundError if no entry matches.
        """
        new_entries: list[BaseBIDEntry] = []
        matched = False
        for entry in self.base_bids:
            if entry.base_bid == base_bid:
                matched = True
                new_entries.append(
                    entry.model_copy(update={"scenarios": [*entry.scenarios, scenario]})
                )
            else:
                new_entries.append(entry)
        if not matched:
            raise BaseBIDNotFoundError(
                f"base_bid {base_bid!r} not found in mapping with project_id={self.project_id!r}"
            )
        return self.model_copy(update={"base_bids": new_entries})

    def append_inspect_journal(
        self, sub_bid: str, entry: InspectJournalEntry
    ) -> MappingArtifact:
        """Return a new MappingArtifact with `entry` appended to inspect_journal[sub_bid].

        Creates the sub_bid key if absent. Parallel to append_scenario.
        """
        new_journal = {k: list(v) for k, v in self.inspect_journal.items()}
        existing = new_journal.get(sub_bid, [])
        new_journal[sub_bid] = [*existing, entry.model_dump(mode="json")]
        return self.model_copy(update={"inspect_journal": new_journal})

    def attach_feature_inspect(self, ref: InspectArtifactRef) -> MappingArtifact:
        """Return a new MappingArtifact with feature_inspect set to ref."""
        return self.model_copy(update={"feature_inspect": ref.model_dump(mode="json")})

    def append_cosmetic(self, feature_id: str, item: CosmeticItem) -> MappingArtifact:
        """Return a new MappingArtifact with item appended to feature_cosmetic_queue
        under the given feature_id."""
        new_dict = item.model_dump(mode="python")
        new_dict["feature_id"] = feature_id
        return self.model_copy(
            update={
                "feature_cosmetic_queue": [
                    *self.feature_cosmetic_queue,
                    new_dict,
                ]
            }
        )

    def feature_resume_state(self) -> dict:
        """Return a snapshot dict describing whether/how to resume this feature.

        Plan 4 only adds the dict shape; Plan 5 uses the "should_resume" semantics.
        """
        halted_states = {"halted", "inspect_pending"}
        return {
            "status": self.feature_status,
            "should_resume": self.feature_status in halted_states,
            "has_inspect_journal": bool(self.inspect_journal),
            "has_feature_inspect": self.feature_inspect is not None,
            "cosmetic_queue_size": len(self.feature_cosmetic_queue),
        }

    async def save(
        self,
        path: Path,
        *,
        events_log: EventsLog | None = None,
    ) -> None:
        async with self._get_save_lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(
                yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)
            )
            tmp_path.replace(path)
        if events_log is not None:
            from datetime import UTC, datetime

            from mage.orchestration.events import Event, EventType

            await events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.MAPPING_SAVED,
                    payload={
                        "feature_cosmetic_queue_size": len(self.feature_cosmetic_queue),
                        "base_bids_count": len(self.base_bids),
                    },
                )
            )

    @classmethod
    def load(cls, path: Path) -> MappingArtifact:
        return cls.model_validate(yaml.safe_load(path.read_text()))
