"""ReviewerAgent base class — shared scaffolding for the 7 reviewer dimensions."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic_ai import Agent

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict, VerdictArtifact
from mage.orchestration.events import EventsLog

if TYPE_CHECKING:
    from mage.state_store import StateStore


def compute_draft_hash(draft: ScenarioSpec, spec_context: dict[str, Any]) -> str:
    """Compute the deterministic SHA-256 hash of (draft, spec_context).

    Used to namespace per-draft verdict storage on disk and to identify the
    same logical draft across reviewer runs. This is the shared algorithm
    used by both ReviewerAgent and InscribeStage; both must call it to
    guarantee the verdict paths match.
    """
    payload = json.dumps(
        {"draft": draft.model_dump(mode="json"), "spec_context": spec_context},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReviewerAgent(ABC):
    """Base class for the 7 reviewer dimensions."""

    dimension: ClassVar[str] = ""

    def __init__(self, model) -> None:
        if not self.dimension:
            raise ValueError(f"{type(self).__name__} must define `dimension`")
        self._agent: Agent[None, ReviewerVerdict] = Agent(
            model, output_type=ReviewerVerdict, system_prompt=self._system_prompt()
        )

    @abstractmethod
    def _system_prompt(self) -> str:
        """Return the dimension-specific rubric and examples."""
        ...

    def _compute_draft_hash(
        self, draft: ScenarioSpec, spec_context: dict[str, Any]
    ) -> str:
        return compute_draft_hash(draft, spec_context)

    async def run(
        self,
        *,
        draft: ScenarioSpec,
        spec_context: dict[str, Any],
        mapping: MappingArtifact,
        events_log: EventsLog,
        state_store: StateStore | None = None,
        verdict_path: Path | str,
    ) -> ReviewerVerdict:
        """Run the reviewer and persist the verdict.

        P32: production callers pass a ``StateStore`` and a relative
        ``verdict_path`` (e.g. ``verdicts/<hash>/<dimension>.yaml``); the
        verdict is written to the orphan branch and the digest event uses
        the relative path. Test-only callers may pass a ``Path`` with
        ``state_store=None``; the legacy working-tree ``finalize`` is used
        in that case so existing tests keep working.
        """
        from mage.state_store import StateStore

        draft_hash = self._compute_draft_hash(draft, spec_context)
        prompt = (
            f"Draft scenario:\n{draft.model_dump_json(indent=2)}\n\n"
            f"Spec context:\n{json.dumps(spec_context, indent=2, default=str)}"
        )
        result = (await self._agent.run(prompt)).output

        result_dict = result.model_dump()
        result_dict.update(
            dimension=self.dimension,
            draft_hash=draft_hash,
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{self.dimension}@v1",
        )
        finalized = ReviewerVerdict.model_validate(result_dict)

        if state_store is not None and isinstance(state_store, StateStore):
            relative_path = str(verdict_path)
            await VerdictArtifact.finalize_to_state_store(
                state_store, relative_path, finalized, events_log
            )
        else:
            await VerdictArtifact.finalize(Path(verdict_path), finalized, events_log)
        return finalized
