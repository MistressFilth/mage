"""InspectArtifact schemas: end-of-feature Inspect content + per-increment journal.

Plan 4 ships the schemas + finalize/load surface; Plan 5 orchestrates the actual
InspectFeatureStage that consumes them. Parallel to Plan 3's verdict.py.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mage.orchestration.events import Event, EventsLog, EventType

if TYPE_CHECKING:
    from mage.state_store import StateStore

# Per-loop / end-of-feature Inspect findings-journal entry.
InspectRoute = Literal["spec", "code", "cosmetic"]


class InspectJournalEntry(BaseModel):
    """One entry in the per-scenario inspect journal."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    feature_id: str = ""
    scenario_id: str = ""
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


class CosmeticFinding(BaseModel):
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
    per_reviewer: list[dict] = Field(
        default_factory=list
    )  # list[ReviewerVerdict] — typing kept loose to avoid circular import
    critical: list[dict] = Field(default_factory=list)  # list[ReviewerFinding]
    important: list[dict] = Field(default_factory=list)
    minor: list[dict] = Field(default_factory=list)
    cross_scenario: list[dict] = Field(default_factory=list)
    ready_to_merge: bool
    ledger_markdown: str = ""


class InspectArtifactError(Exception):
    """Base exception for InspectArtifact errors."""


class InspectArtifactDigestMismatchError(InspectArtifactError):
    """Raised when load() finds the on-disk digest doesn't match the recorded digest."""


class InspectArtifact:
    """Digest-pinned Inspect operations, parallel to VerdictArtifact."""

    @staticmethod
    def _compute_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _latest_event_for_path(
        events_log: EventsLog, path: Path, event_types: tuple[EventType, ...]
    ) -> Event | None:
        path_str = str(path)
        candidates = [
            e
            for e in events_log.read_all()
            if e.event_type in event_types and e.payload.get("inspect_path") == path_str
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.timestamp)

    @classmethod
    async def finalize(
        cls, path: Path, content: InspectArtifactContent, events_log: EventsLog
    ) -> str:
        """Write Inspect YAML atomically, compute SHA256, emit INSPECT_FEATURE_FINALIZED.

        Returns inspect_sha256.
        """
        digest = cls._compute_digest(
            yaml.safe_dump(content.model_dump(mode="json"), sort_keys=False)
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            yaml.safe_dump(content.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        tmp_path.replace(path)

        await events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_FINALIZED,
                payload={
                    "inspect_path": str(path),
                    "inspect_sha256": digest,
                    "feature_id": content.feature_id,
                    "iteration": content.iteration,
                    "ready_to_merge": content.ready_to_merge,
                },
            )
        )
        return digest

    @classmethod
    async def finalize_to_state_store(
        cls,
        state_store: StateStore,
        relative_path: str,
        content: InspectArtifactContent,
        events_log: EventsLog,
    ) -> str:
        """Write Inspect YAML to the orphan branch via ``state_store`` (P32).

        Serializes the content, computes SHA256, writes via ``state_store.write``,
        and emits ``INSPECT_FEATURE_FINALIZED`` with the canonical payload.
        ``relative_path`` is the orphan-branch-relative path (e.g.
        ``inspect/<feature_id>/<iteration>.yaml``).

        Returns inspect_sha256.
        """
        from mage.state_store import StateStore

        if not isinstance(state_store, StateStore):
            raise TypeError(
                f"state_store must be a StateStore; got {type(state_store).__name__}"
            )
        payload = yaml.safe_dump(content.model_dump(mode="json"), sort_keys=False)
        digest = cls._compute_digest(payload)
        state_store.write(relative_path, payload.encode("utf-8"))

        await events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_FINALIZED,
                payload={
                    "inspect_path": relative_path,
                    "inspect_sha256": digest,
                    "feature_id": content.feature_id,
                    "iteration": content.iteration,
                    "ready_to_merge": content.ready_to_merge,
                },
            )
        )
        return digest

    @classmethod
    async def load_from_state_store(
        cls,
        state_store: StateStore,
        relative_path: str,
        events_log: EventsLog,
    ) -> InspectArtifactContent:
        """Read InspectArtifact from the orphan branch via ``state_store`` (P32).

        Reads the bytes via ``state_store.read(relative_path)``, verifies the
        digest against the most recent ``INSPECT_FEATURE_FINALIZED`` event for
        that path, and returns the parsed ``InspectArtifactContent``.

        Raises ``InspectArtifactError`` if no event is recorded for the path
        (refuses to read unwitnessed bytes), or if the digest does not match.
        """
        from mage.state_store import StateStore

        if not isinstance(state_store, StateStore):
            raise TypeError(
                f"state_store must be a StateStore; got {type(state_store).__name__}"
            )
        event = cls._latest_event_for_relative_path(
            events_log, relative_path, (EventType.INSPECT_FEATURE_FINALIZED,)
        )
        if event is None:
            raise InspectArtifactError(
                f"No INSPECT_FEATURE_FINALIZED event for {relative_path}; "
                "refusing to read."
            )

        recorded_digest = event.payload.get("inspect_sha256")
        if recorded_digest is None:
            raise InspectArtifactError(
                f"Event for {relative_path} has no inspect_sha256 in payload"
            )

        raw = state_store.read(relative_path)
        if not raw:
            raise InspectArtifactError(
                f"InspectArtifact file {relative_path} is absent on the orphan branch"
            )

        content = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        computed = cls._compute_digest(content)

        if computed != recorded_digest:
            await events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.PLAN_DIGEST_MISMATCH,
                    payload={
                        "inspect_path": relative_path,
                        "recorded_sha256": recorded_digest,
                        "computed_sha256": computed,
                    },
                )
            )
            raise InspectArtifactDigestMismatchError(
                f"InspectArtifact at {relative_path} digest mismatch: "
                f"recorded={recorded_digest}, computed={computed}"
            )

        data = yaml.safe_load(content)
        return InspectArtifactContent.model_validate(data)

    @staticmethod
    def _latest_event_for_relative_path(
        events_log: EventsLog, relative_path: str, event_types: tuple[EventType, ...]
    ) -> Event | None:
        candidates = [
            e
            for e in events_log.read_all()
            if e.event_type in event_types
            and e.payload.get("inspect_path") == relative_path
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.timestamp)

    @classmethod
    async def load(cls, path: Path, events_log: EventsLog) -> InspectArtifactContent:
        """Read InspectArtifact with digest verification."""
        event = cls._latest_event_for_path(
            events_log, path, (EventType.INSPECT_FEATURE_FINALIZED,)
        )
        if event is None:
            raise InspectArtifactError(
                f"No INSPECT_FEATURE_FINALIZED event for {path}; refusing to read."
            )

        recorded_digest = event.payload.get("inspect_sha256")
        if recorded_digest is None:
            raise InspectArtifactError(
                f"Event for {path} has no inspect_sha256 in payload"
            )

        if not path.exists():
            raise InspectArtifactError(
                f"InspectArtifact file {path} does not exist on disk"
            )

        content = path.read_text(encoding="utf-8")
        computed = cls._compute_digest(content)

        if computed != recorded_digest:
            await events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.PLAN_DIGEST_MISMATCH,  # reuse existing event type
                    payload={
                        "inspect_path": str(path),
                        "recorded_sha256": recorded_digest,
                        "computed_sha256": computed,
                    },
                )
            )
            raise InspectArtifactDigestMismatchError(
                f"InspectArtifact at {path} digest mismatch: "
                f"recorded={recorded_digest}, computed={computed}"
            )

        data = yaml.safe_load(content)
        return InspectArtifactContent.model_validate(data)
