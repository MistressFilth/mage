"""InspectArtifact schemas: end-of-feature Inspect content + per-increment journal.

Plan 4 ships the schemas + finalize/load surface; Plan 5 orchestrates the actual
InspectFeatureStage that consumes them. Parallel to Plan 3's verdict.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Per-loop / end-of-feature Inspect findings-journal entry.
InspectRoute = Literal["spec", "code", "cosmetic"]


class InspectJournalEntry(BaseModel):
    """One entry in the per-scenario inspect journal."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    iteration: int
    dimension: str  # "mechanical" | "increment_quality" | "<reviewer_dimension>"
    severity: Literal["critical", "major", "minor"]
    route: InspectRoute  # only relevant for non-mechanical entries
    finding_id: str
    location: str
    issue: str
    rationale: str


# Per-scenario status after a feature-level Inspect pass.
ScenarioInspectStatusValue = Literal["live", "needs_refactor", "approved_with_caveat"]


class ScenarioInspectStatus(BaseModel):
    """Per-scenario status emitted by InspectFeatureStage."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    scenario_name: str
    status: ScenarioInspectStatusValue


class CosmeticItem(BaseModel):
    """Natural-language cosmetic item queued for human review."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    scenario_name: str
    location: str
    text: str
    proposed_by: str  # "increment_quality" | "<reviewer_dimension>"


class InspectArtifactRef(BaseModel):
    """Digest-pinned reference to an InspectArtifact file on disk."""

    model_config = ConfigDict(frozen=True)

    inspect_path: str
    inspect_sha256: str
    finalized_at: datetime


class InspectArtifactContent(BaseModel):
    """End-of-feature Inspect content. The digest is NOT a field here —
    it's the event payload key `inspect_sha256` (per GC-7 / spec R24).
    """

    model_config = ConfigDict(frozen=True)

    feature_id: str
    inspected_at: datetime
    iteration: int
    eof_max_iterations: int
    scenarios: list[ScenarioInspectStatus] = Field(default_factory=list)
    per_reviewer: list[dict] = Field(default_factory=list)  # list[ReviewerVerdict] — typing kept loose to avoid circular import
    critical: list[dict] = Field(default_factory=list)  # list[ReviewerFinding]
    important: list[dict] = Field(default_factory=list)
    minor: list[dict] = Field(default_factory=list)
    cross_scenario: list[dict] = Field(default_factory=list)
    ready_to_merge: bool
    ledger_markdown: str = ""
