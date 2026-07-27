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

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import LifecycleStatus, MappingArtifact


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


class StepDefinitionsResolvableCheck(MechanicalCheck):
    """Validates that every step maps to a registered step-definition pattern."""

    name = "step-definitions-resolvable"

    def __init__(self, registered_patterns: list[re.Pattern[str]]) -> None:
        super().__init__()
        self.registered_patterns = registered_patterns

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        unresolvable = []
        for step in draft.step_texts:
            if not any(p.search(step) for p in self.registered_patterns):
                unresolvable.append(step)
        if unresolvable:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"unresolvable steps: {'; '.join(unresolvable)}",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)


class LifecycleStatusTagPresentCheck(MechanicalCheck):
    """Validates that the scenario has a valid lifecycle status tag."""

    name = "lifecycle-status-tag-present"

    PREFIX = "@status-"
    VALID_VALUES = {s.value for s in LifecycleStatus}

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        lifecycle_tags = [t for t in draft.tags if t.startswith(self.PREFIX)]
        if not lifecycle_tags:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail="missing lifecycle status tag (e.g. @status-inscribing)",
            )
        invalid = [t for t in lifecycle_tags if t[len(self.PREFIX):] not in self.VALID_VALUES]
        if invalid:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"invalid lifecycle tag(s): {', '.join(invalid)}",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)


class SubBidAssignedCheck(MechanicalCheck):
    """Validates sub-BID format (Base85) and parent base-BID existence."""

    name = "sub-bid-assigned"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        # Validate sub-BID is in Base85 alphabet.
        try:
            Base85BID(value=draft.sub_bid)
        except ValueError as e:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"sub-BID not in Base85 alphabet: {e}",
            )
        # Validate parent base-BID exists in mapping.
        parent = draft.parent_base_bid.value
        if not any(entry.base_bid == parent for entry in mapping.base_bids):
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"parent base-BID {parent} not found in mapping artifact",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)


class CrossBehaviorTagsValidCheck(MechanicalCheck):
    """Validates that @behavior-X tags reference existing behaviors."""

    name = "cross-behavior-tags-valid"

    PREFIX = "@behavior-"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        cross_tags = [t for t in draft.tags if t.startswith(self.PREFIX)]
        if not cross_tags:
            return CheckResult(name=self.name, outcome="pass", detail=None)
        existing = {entry.base_bid for entry in mapping.base_bids}
        dangling = [
            t for t in cross_tags
            if t[len(self.PREFIX):] not in existing
        ]
        if dangling:
            return CheckResult(
                name=self.name,
                outcome="fail",
                detail=f"cross-behavior tags reference unknown behaviors: {', '.join(dangling)}",
            )
        return CheckResult(name=self.name, outcome="pass", detail=None)
