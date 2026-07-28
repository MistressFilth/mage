"""Verdict schemas: per-reviewer + aggregate, digest-pinned via VerdictArtifact."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewerFinding(BaseModel):
    """A single finding from a reviewer."""

    model_config = ConfigDict(frozen=True)

    id: str
    severity: Literal["critical", "major", "minor"]
    location: str
    issue: str
    rationale: str
    suggestion: str = ""
    citations: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must be non-empty")
        return v


class ReviewerVerdict(BaseModel):
    """Per-reviewer verdict: one dimension, one outcome, list of findings."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    outcome: Literal["pass", "fail"]
    draft_hash: str
    reviewed_at: datetime
    reviewer_id: str
    findings: list[ReviewerFinding] = Field(default_factory=list)
    notes: str = ""


class DimensionSummary(BaseModel):
    """One entry in an aggregate's per_dimension map."""

    model_config = ConfigDict(frozen=True)

    outcome: Literal["pass", "fail"]
    reviewer_verdict_ref: str
    findings_count: int


class ReviewerAggregate(BaseModel):
    """Aggregate of all 7 reviewer verdicts for one draft iteration."""

    model_config = ConfigDict(frozen=True)

    draft_hash: str
    aggregated_at: datetime
    iteration: int
    per_dimension: dict[str, DimensionSummary]
    decision: Literal["approved", "needs_refactor", "needs_human_review"]
    reasoning: str = ""
