"""ReviewerAgent base class — shared scaffolding for the 7 reviewer dimensions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic_ai import Agent

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict, VerdictArtifact
from mage.orchestration.events import EventsLog


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

    def _compute_draft_hash(self, draft: ScenarioSpec, spec_context: dict[str, Any]) -> str:
        payload = json.dumps(
            {"draft": draft.model_dump(mode="json"), "spec_context": spec_context},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def run(self, *, draft: ScenarioSpec, spec_context: dict[str, Any], mapping: MappingArtifact,
            events_log: EventsLog, verdict_path: Path) -> ReviewerVerdict:
        draft_hash = self._compute_draft_hash(draft, spec_context)
        prompt = (f"Draft scenario:\n{draft.model_dump_json(indent=2)}\n\n"
                  f"Spec context:\n{json.dumps(spec_context, indent=2, default=str)}")
        result = self._agent.run_sync(prompt).output

        result_dict = result.model_dump()
        result_dict.update(dimension=self.dimension, draft_hash=draft_hash,
                           reviewed_at=datetime.now(UTC), reviewer_id=f"{self.dimension}@v1")
        finalized = ReviewerVerdict.model_validate(result_dict)
        VerdictArtifact.finalize(verdict_path, finalized, events_log)
        return finalized
