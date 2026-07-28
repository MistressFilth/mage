"""Project-level mapping artifact: single source of truth for BIDs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mage.artifacts.bid import Base85BID, next_base_bid


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
    schema_version: int = 1
    project_id: str
    base_bids: list[BaseBIDEntry] = Field(default_factory=list)

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

    def append_scenario(self, base_bid: str, scenario: "ScenarioEntry") -> "MappingArtifact":
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

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False))
        tmp_path.replace(path)

    @classmethod
    def load(cls, path: Path) -> "MappingArtifact":
        return cls.model_validate(yaml.safe_load(path.read_text()))
