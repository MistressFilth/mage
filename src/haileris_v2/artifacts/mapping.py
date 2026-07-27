"""Project-level mapping artifact: single source of truth for BIDs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from haileris_v2.artifacts.bid import BASE85_ALPHABET, BASE_BID_LENGTH, Base85BID


class LifecycleStatus(str, Enum):
    INSCRIBING = "inscribing"
    APPROVED = "approved"
    LIVE = "live"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


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
        highest = self.highest_base_bid()
        if highest is None:
            return Base85BID(value="0" * BASE_BID_LENGTH)
        padded = highest.value.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])
        return Base85BID(value=padded).increment()

    def lookup_sub_bid(self, base: Base85BID, sub: str) -> ScenarioEntry | None:
        for entry in self.base_bids:
            if entry.base_bid == base.value:
                for scenario in entry.scenarios:
                    if scenario.sub_bid == sub:
                        return scenario
        return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False))
        tmp_path.replace(path)

    @classmethod
    def load(cls, path: Path) -> "MappingArtifact":
        return cls.model_validate(yaml.safe_load(path.read_text()))
