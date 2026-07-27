"""Mechanical author verification — deterministic pre-filter for the spec gate.

Per spec Pivot #4, this layer runs immediately after the author agent drafts a
scenario. No LLM calls — pure structural/grammatical/syntactic validation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from haileris_v2.artifacts.bid import Base85BID
from haileris_v2.artifacts.mapping import MappingArtifact


class ScenarioDraft(BaseModel):
    """The input to mechanical verification: a freshly drafted scenario."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    feature_path: Path
    scenario_name: str
    gherkin_text: str
    tags: list[str] = Field(default_factory=list)
    sub_bid: str
    parent_base_bid: Base85BID
    step_texts: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    """Outcome of one mechanical check."""

    model_config = ConfigDict(frozen=True)

    name: str
    outcome: Literal["pass", "fail"]
    detail: str | None = None


class MechanicalCheck(ABC):
    """Abstract base for mechanical checks.

    Subclasses must define `name` and implement `_run()`.
    """

    name: str = ""

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define `name`")

    def run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        """Execute the check (validates name, then delegates to _run)."""
        return self._run(draft, mapping)

    @abstractmethod
    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        ...


class MechanicalVerifier:
    """Runs a set of mechanical checks against a scenario draft."""

    def __init__(self, checks: list[MechanicalCheck]) -> None:
        self.checks = list(checks)

    def verify(self, draft: ScenarioDraft, mapping: MappingArtifact) -> list[CheckResult]:
        """Run all registered checks. Returns one CheckResult per check."""
        return [check.run(draft, mapping) for check in self.checks]

    def all_passed(self, results: list[CheckResult]) -> bool:
        """True iff every check passed."""
        return all(r.outcome == "pass" for r in results)
