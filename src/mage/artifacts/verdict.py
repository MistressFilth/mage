"""Verdict schemas: per-reviewer + aggregate, digest-pinned via VerdictArtifact."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Routing for Inspect loop. Defined locally to avoid pulling
# mage.orchestration.inspect_loop into the artifact layer (cycle) and to
# keep the dependency direction: artifacts -> nothing internal.
InspectRoute = Literal["spec", "code", "cosmetic"]


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
    # Route is meaningful only for the per-loop Inspect reviewer
    # (IncrementQualityReviewer). The default keeps the standard 7-reviewer
    # Inscribe findings backward-compatible: findings carry the code route
    # unless the reviewer explicitly sets spec/cosmetic. InspectLoopStage
    # reads this field directly — no more suggestion-prefix parsing.
    route: InspectRoute = "code"

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


class VerdictError(Exception):
    """Base exception for VerdictArtifact errors."""


class VerdictDigestMismatchError(VerdictError):
    """Raised when load() finds the on-disk digest doesn't match the recorded digest."""


class VerdictArtifact:
    """Digest-pinned Verdict operations.

    Mirrors PlanArtifact's API surface — same atomic write, same digest mechanism,
    same event emission. Storage layout is determined by the caller (paths passed in).
    """

    @staticmethod
    def _compute_digest(content: str) -> str:
        import hashlib
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _latest_event_for_path(
        events_log: "EventsLog", path, event_types: tuple,
    ):
        path_str = str(path)
        candidates = [
            e for e in events_log.read_all()
            if e.event_type in event_types
            and e.payload.get("verdict_path") == path_str
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.timestamp)

    @classmethod
    def finalize(cls, path, model: BaseModel, events_log) -> str:
        """Write verdict/aggregate to YAML at `path`, compute SHA256, emit event.

        For ReviewerVerdict → emits REVIEWER_VERDICT_RECORDED.
        For ReviewerAggregate → emits REVIEW_AGGREGATE_RECORDED.
        """
        import yaml
        from datetime import datetime, UTC
        from mage.orchestration.events import Event  # local import to avoid cycle

        content = yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False)
        digest = cls._compute_digest(content)

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

        if isinstance(model, ReviewerAggregate):
            event_type_value = "review_aggregate_recorded"
        else:
            event_type_value = "reviewer_verdict_recorded"

        from mage.orchestration.events import EventType
        event_type = EventType(event_type_value)
        events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=event_type,
                payload={
                    "verdict_path": str(path),
                    "verdict_sha256": digest,
                    "dimension": getattr(model, "dimension", None),
                    "outcome": getattr(model, "outcome", None) or getattr(model, "decision", None),
                },
            )
        )
        return digest

    @classmethod
    def load(cls, path, events_log) -> BaseModel:
        """Load verdict/aggregate with digest verification against the most recent event.

        Returns the original Pydantic model (ReviewerVerdict or ReviewerAggregate).
        """
        import yaml
        from mage.orchestration.events import EventType
        from mage.orchestration.events import Event

        event = cls._latest_event_for_path(
            events_log, path,
            (EventType.REVIEWER_VERDICT_RECORDED, EventType.REVIEW_AGGREGATE_RECORDED),
        )
        if event is None:
            raise VerdictError(
                f"No REVIEWER_VERDICT_RECORDED/REVIEW_AGGREGATE_RECORDED event for {path}"
            )

        recorded_digest = event.payload.get("verdict_sha256")
        if recorded_digest is None:
            raise VerdictError(f"Event for {path} has no verdict_sha256 in payload")

        if not path.exists():
            raise VerdictError(f"Verdict file {path} does not exist on disk")

        content = path.read_text(encoding="utf-8")
        computed = cls._compute_digest(content)

        if computed != recorded_digest:
            events_log.append(
                Event(
                    timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    event_type=EventType.PLAN_DIGEST_MISMATCH,  # reuse existing event type
                    payload={
                        "verdict_path": str(path),
                        "recorded_sha256": recorded_digest,
                        "computed_sha256": computed,
                    },
                )
            )
            raise VerdictDigestMismatchError(
                f"Verdict at {path} digest mismatch: "
                f"recorded={recorded_digest}, computed={computed}"
            )

        data = yaml.safe_load(content)
        # Decide which model class to reconstruct based on shape.
        if "per_dimension" in data:
            return ReviewerAggregate.model_validate(data)
        return ReviewerVerdict.model_validate(data)
