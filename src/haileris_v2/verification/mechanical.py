"""Mechanical author verification — deterministic pre-filter for the spec gate.

Per spec Pivot #4, this layer runs immediately after the author agent drafts a
scenario. No LLM calls — pure structural/grammatical/syntactic validation.
"""

from __future__ import annotations

import re
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


class GherkinSyntaxCheck(MechanicalCheck):
    """Validates Gherkin structure: Given, When, Then all present."""

    name = "gherkin-syntax"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        steps = draft.step_texts
        if not steps:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail="scenario has no steps",
            )
        keywords = {step.split()[0] for step in steps if step.strip()}
        missing = [k for k in ("Given", "When", "Then") if k not in keywords]
        if missing:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"missing required step keywords: {', '.join(missing)}",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)


class ScenarioNameUniqueCheck(MechanicalCheck):
    """Validates that the scenario name is unique within its feature file."""

    name = "scenario-name-unique"

    SCENARIO_PATTERN = re.compile(r"^\s*Scenario:\s*(.+?)\s*$", re.MULTILINE)

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        if not draft.feature_path.exists():
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"feature file does not exist: {draft.feature_path}",
            )
        text = draft.feature_path.read_text()
        names = self.SCENARIO_PATTERN.findall(text)
        # Normalize for comparison (Gherkin scenario names can have trailing descriptions).
        normalized = [n.split("(")[0].strip() for n in names]
        target = draft.scenario_name.split("(")[0].strip()
        duplicates = [n for n in normalized if n == target]
        if len(duplicates) > 1:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"duplicate scenario name '{draft.scenario_name}' in feature file",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)


class TagsRegisteredCheck(MechanicalCheck):
    """Validates that all tags on the scenario are registered."""

    name = "tags-registered"

    def __init__(self, registered_tags: set[str]) -> None:
        super().__init__()
        self.registered_tags = registered_tags

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        unregistered = [t for t in draft.tags if t not in self.registered_tags]
        if unregistered:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"unregistered tags: {', '.join(unregistered)}",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)
