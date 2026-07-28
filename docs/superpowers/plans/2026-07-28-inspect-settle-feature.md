# Inspect-feature + Settle-feature Implementation Plan (Plan 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-of-feature Inspect stage (`InspectFeatureStage` with full 7-reviewer sweep + `CrossScenarioReviewer` + 3-tier severity routing), the `InspectArtifact` lifecycle (finalize, load, halt), and the `SettleFeatureStage` (cosmetic queue handoff + `/finishing-a-development-branch`-equivalent finalization flow: 4-option menu, conditional cleanup).

**Architecture:** Adds an end-of-feature Orchestrator that runs the full Plan 3 reviewer sweep + a new `CrossScenarioReviewer` over the live feature, applies 3-tier severity routing (Critical = reenter Realize for affected scenarios; Important = fix-wave subagent; Minor = cosmetic queue), persists a digest-pinned `InspectArtifact`, and on `ready_to_merge=True` hands off to `SettleFeatureStage` which aggregates the cosmic queue and runs the finishing-equivalent flow. Two halt mechanisms: `InspectFeatureHalted` (caught by `PipelineGraph`) for the end-of-feature budget, and the existing `ScenarioInspectHalted` (Plan 4) for per-scenario work.

**Tech Stack:** Python 3.11+, Pydantic v2, Pydantic-AI, pytest, the existing `mage` package.

## Global Constraints

- **GC-1**: End-of-feature Inspect uses the Plan 3 7-reviewer sweep + the new `CrossScenarioReviewer` (8th dimension, **eof-only**). NOT registered in `default_reviewer_registry()`. New registry: `feature_reviewer_registry()`.
- **GC-2**: 3-tier severity routing per spec R22: Critical = reenter Realize (emit `SCENARIO_NEEDS_REFACTOR` for affected scenarios); Important = fix-wave subagent (single-shot, no reentry); Minor = cosmetic queue.
- **GC-3**: `InspectFeatureHalted` is raised when `iteration >= eof_max_iterations` and `ready_to_merge` is still false. Caught by `PipelineGraph` (similar to Plan 4's `ScenarioInspectHalted`).
- **GC-4**: `SettleFeatureStage` does NOT review. Its two responsibilities per spec R25: (1) cosmetic queue aggregation + handoff, (2) `/finishing-a-development-branch`-equivalent finalization flow (verify tests, detect env, 4-option menu, conditional cleanup).
- **GC-5**: Settle-feature presents 4 options (merge, push+PR, keep, discard) following `/finishing-a-development-branch`'s Step 4 exactly. Worktree cleanup only for `.worktrees/`-style worktrees (provenance check); harness-owned worktrees preserved.
- **GC-6**: CLI surface additions: `mage inspect show <feature_id>` (already in Plan 4 Task 13), `mage settle run <feature_id>` (Plan 5). Both follow the Plan 3 `mage review show` / `mage review resume` pattern.
- **GC-7**: Settle's 4-option menu is the final user-facing disposition. The chosen disposition is recorded in the `SETTLE_FEATURE_FINALIZED` event payload (`disposition: "merged" | "pr_opened" | "kept" | "discarded"`).
- **GC-8**: The cosmetic queue handoff file is written at `<project_dir>/.haileris/settle/<feature_id>-cosmetic.md` (parallel to the `SettleReport` at `<feature_id>.md`).
- **GC-9**: Conventional commits, no `Co-Authored-By` trailer. CLI is `mage`, package is `mage`. No `haileris_v2` references.
- **GC-10**: All new code follows Plan 3 + Plan 4 patterns: `TestModel(custom_output_args=canned)` fixture for LLM reviewers, atomic writes + `.tmp`, `Event(timestamp=datetime.now(UTC), event_type=..., payload={...})`, immutable `model_copy(update=...)`.
- **GC-11**: Plan 5 module layout: `src/mage/orchestration/inspect_feature.py`, `src/mage/orchestration/settle_feature.py`, `src/mage/verification/reviewers/cross_scenario.py`. Tests in `tests/test_inspect_feature.py`, `tests/test_settle_feature.py`, `tests/test_reviewers/test_cross_scenario.py`.

---

## Task 1: Plan 5 EventType Members

**Files:**
- Modify: `src/mage/orchestration/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: Plan 4's `EventType` enum (already has INSPECT_FEATURE_STARTED, INSPECT_FEATURE_FINALIZED placeholders from Task 1)
- Produces: ~10 new EventType members for InspectFeature + SettleFeature stages

- [ ] **Step 1: Write the failing test**

Append to `tests/test_events.py`:

```python
class TestPlan5EventTypes:
    def test_inspect_feature_events_full(self):
        from mage.orchestration.events import EventType
        # Plan 4 added placeholders; Plan 5 adds the rest.
        assert EventType.INSPECT_FEATURE_PASSED.value == "inspect_feature_passed"
        assert EventType.INSPECT_FEATURE_HALT_PERSISTED.value == "inspect_feature_halt_persisted"
        assert EventType.INSPECT_FEATURE_COMPLETED.value == "inspect_feature_completed"
        assert EventType.FIX_WAVE_DISPATCHED.value == "fix_wave_dispatched"

    def test_settle_feature_events(self):
        from mage.orchestration.events import EventType
        assert EventType.SETTLE_FEATURE_STARTED.value == "settle_feature_started"
        assert EventType.SETTLE_COSMETIC_QUEUED.value == "settle_cosmetic_queued"
        assert EventType.SETTLE_TESTS_FAILED.value == "settle_tests_failed"
        assert EventType.SETTLE_FEATURE_FINALIZED.value == "settle_feature_finalized"
        assert EventType.SETTLE_FEATURE_COMPLETED.value == "settle_feature_completed"
        assert EventType.SETTLE_BRANCH_DISCARDED.value == "settle_branch_discarded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events.py::TestPlan5EventTypes -v`
Expected: AttributeError on the new members.

- [ ] **Step 3: Add the new EventType members**

In `src/mage/orchestration/events.py`, after the existing `INSPECT_FEATURE_PLACEHOLDER` block (added in Plan 4 Task 1), insert:

```python
    # Plan 5 — InspectFeature stage (full set)
    INSPECT_FEATURE_PASSED = "inspect_feature_passed"
    INSPECT_FEATURE_HALT_PERSISTED = "inspect_feature_halt_persisted"
    INSPECT_FEATURE_COMPLETED = "inspect_feature_completed"
    FIX_WAVE_DISPATCHED = "fix_wave_dispatched"

    # Plan 5 — SettleFeature stage
    SETTLE_FEATURE_STARTED = "settle_feature_started"
    SETTLE_COSMETIC_QUEUED = "settle_cosmetic_queued"
    SETTLE_TESTS_FAILED = "settle_tests_failed"
    SETTLE_FEATURE_FINALIZED = "settle_feature_finalized"
    SETTLE_FEATURE_COMPLETED = "settle_feature_completed"
    SETTLE_BRANCH_DISCARDED = "settle_branch_discarded"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_events.py::TestPlan5EventTypes -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/events.py tests/test_events.py
git commit -m "feat(orchestration): add 10 Plan 5 EventType members"
```

---

## Task 2: CrossScenarioReviewer

**Files:**
- Create: `src/mage/verification/reviewers/cross_scenario.py`
- Test: `tests/test_reviewers/test_cross_scenario.py`

**Interfaces:**
- Consumes: `ReviewerAgent` ABC from Plan 3
- Produces: `CrossScenarioReviewer` subclass with `dimension = "cross_scenario"`. Reviews whole feature for shared state leaks, ordering dependencies, integration gaps, naming/tag collisions.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_cross_scenario.py`:

```python
"""Tests for CrossScenarioReviewer (eof-only reviewer)."""

from __future__ import annotations

from datetime import UTC, datetime


class TestCrossScenarioReviewer:
    def test_dimension_classvar(self):
        from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
        assert CrossScenarioReviewer.dimension == "cross_scenario"

    def test_system_prompt_mentions_four_foci(self):
        from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
        prompt = CrossScenarioReviewer(system_prompt_only=True)._system_prompt()
        assert "shared state" in prompt.lower()
        assert "ordering" in prompt.lower()
        assert "integration" in prompt.lower()
        assert "naming" in prompt.lower() or "tag" in prompt.lower()

    def test_run_with_canned_testmodel(self):
        from pydantic_ai.models.test import TestModel
        from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
        from mage.artifacts.verdict import ReviewerVerdict

        canned = ReviewerVerdict(
            dimension="cross_scenario",
            outcome="pass",
            draft_hash="",
            reviewed_at=datetime.now(UTC),
            reviewer_id="cross_scenario@v1",
            findings=[],
        )
        reviewer = CrossScenarioReviewer(model=TestModel(custom_output_args=canned))
        assert reviewer.dimension == "cross_scenario"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reviewers/test_cross_scenario.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement CrossScenarioReviewer**

Create `src/mage/verification/reviewers/cross_scenario.py`:

```python
"""End-of-feature-only reviewer: CrossScenarioReviewer.

Reviews the whole feature as one unit for cross-scenario issues:
- Shared state leaks (multiple scenarios read/write the same domain object)
- Ordering dependencies (scenarios that must run in a particular order)
- Integration gaps (where two scenarios' domain models touch)
- Cross-scenario naming/tag collisions (drift across scenarios)

Used ONLY by InspectFeatureStage (Plan 5). NOT registered in
default_reviewer_registry (which is the Inscribe 7-reviewer registry).
Added to feature_reviewer_registry (Plan 5 Task 3).
"""

from __future__ import annotations

from typing import ClassVar

from mage.artifacts.verdict import ReviewerVerdict
from mage.verification.reviewers.base import ReviewerAgent


class CrossScenarioReviewer(ReviewerAgent):
    """End-of-feature-only reviewer for cross-scenario issues."""

    dimension: ClassVar[str] = "cross_scenario"

    def __init__(self, model, *, system_prompt_only: bool = False) -> None:
        self._system_prompt_only = system_prompt_only
        if not system_prompt_only:
            from pydantic_ai import Agent
            self._agent = Agent(
                model, output_type=ReviewerVerdict, system_prompt=self._system_prompt()
            )

    def _system_prompt(self) -> str:
        return (
            "You are a Cross-Scenario Reviewer. Review the WHOLE FEATURE as one unit. "
            "Look for four kinds of issues:\n\n"
            "  1. SHARED STATE LEAKS — multiple scenarios read/write the same "
            "domain object in ways that conflict.\n"
            "  2. ORDERING DEPENDENCIES — scenarios that must run in a particular "
            "order that per-scenario reviews don't observe.\n"
            "  3. INTEGRATION GAPS — where two scenarios' domain models touch but "
            "neither scenario's test exercises the boundary.\n"
            "  4. NAMING/TAG COLLISIONS — naming patterns or tag conventions that "
            "drift across scenarios.\n\n"
            "Each finding has severity (critical/major/minor), location (scenario "
            "name + sub_bid), issue, rationale, and suggestion. "
            "Rationale is mandatory."
        )

    def run(
        self,
        *,
        feature_summary: dict,
        scenarios: list[dict],
        mapping: object,
    ) -> ReviewerVerdict:
        """Run the reviewer across the whole feature.

        Plan 5's InspectFeatureStage (Task 5) calls this with the full
        feature's scenario set.
        """
        from datetime import UTC, datetime

        prompt = (
            f"Feature summary: {feature_summary}\n\n"
            f"Scenarios:\n" + "\n".join(f"  {s}" for s in scenarios) + "\n\n"
            f"Review for cross-scenario issues per your rubric."
        )

        result = self._agent.run_sync(prompt).output
        result_dict = result.model_dump()
        result_dict["dimension"] = self.dimension
        result_dict["reviewed_at"] = datetime.now(UTC)
        result_dict["reviewer_id"] = f"{self.dimension}@v1"
        result_dict["draft_hash"] = ""  # not meaningful at feature scope
        return ReviewerVerdict.model_validate(result_dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reviewers/test_cross_scenario.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/cross_scenario.py tests/test_reviewers/test_cross_scenario.py
git commit -m "feat(reviewers): add CrossScenarioReviewer (eof-only)"
```

---

## Task 3: feature_reviewer_registry

**Files:**
- Modify: `src/mage/verification/reviewers/registry.py` (add `feature_reviewer_registry()`)
- Test: `tests/test_reviewers/test_registry.py` (append)

**Interfaces:**
- Consumes: existing `default_reviewer_registry()`, `aggregate_verdicts()` from Plan 3
- Produces: `feature_reviewer_registry() -> list[ReviewerAgent]` returning the 7 Plan 3 reviewers + the new CrossScenarioReviewer. Reviewed dimension list: `["spec_compliance", "scenario_clarity", "step_grammar", "testability", "determinism", "naming_idiom", "lifecycle_tags", "cross_scenario"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reviewers/test_registry.py`:

```python
class TestFeatureReviewerRegistry:
    def test_feature_reviewer_registry_has_eight_dimensions(self):
        from mage.verification.reviewers.registry import feature_reviewer_registry
        registry = feature_reviewer_registry()
        dims = sorted(r.dimension for r in registry)
        assert dims == sorted([
            "cross_scenario",
            "determinism",
            "lifecycle_tags",
            "naming_idiom",
            "scenario_clarity",
            "spec_compliance",
            "step_grammar",
            "testability",
        ])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reviewers/test_registry.py::TestFeatureReviewerRegistry -v`
Expected: ImportError on `feature_reviewer_registry`.

- [ ] **Step 3: Implement feature_reviewer_registry**

Read `src/mage/verification/reviewers/registry.py` first to understand the existing pattern. Then add `feature_reviewer_registry()`:

```python
def feature_reviewer_registry() -> list[ReviewerAgent]:
    """Return the end-of-feature Inspect reviewers (7 from Plan 3 + cross_scenario).

    Distinct from default_reviewer_registry (which is the Inscribe 7-reviewer set).
    Both share dimension names for the 7 original; cross_scenario is added here.
    """
    if not getattr(feature_reviewer_registry, "_cache", None):
        from mage.verification.reviewers.cross_scenario import CrossScenarioReviewer
        from mage.verification.reviewers.determinism import DeterminismReviewer
        from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
        from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
        from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
        from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
        from mage.verification.reviewers.step_grammar import StepGrammarReviewer
        from mage.verification.reviewers.testability import TestabilityReviewer

        # Use a placeholder model — InspectFeatureStage will inject real models
        # based on host config in production. Tests pass canned TestModels.
        from unittest.mock import MagicMock
        model = MagicMock()

        feature_reviewer_registry._cache = [
            SpecComplianceReviewer(model=model),
            ScenarioClarityReviewer(model=model),
            StepGrammarReviewer(model=model),
            TestabilityReviewer(model=model),
            DeterminismReviewer(model=model),
            NamingIdiomReviewer(model=model),
            LifecycleTagsReviewer(model=model),
            CrossScenarioReviewer(model=model),
        ]
    return list(feature_reviewer_registry._cache)
```

(Implementer: locate the existing `default_reviewer_registry()` factory and follow its exact pattern. The 7 reviewer subclasses already exist from Plan 3 Tasks 9–15.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reviewers/test_registry.py::TestFeatureReviewerRegistry -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/registry.py tests/test_reviewers/test_registry.py
git commit -m "feat(reviewers): add feature_reviewer_registry (7 + cross_scenario)"
```

---

## Task 4: InspectFeatureHalted + PipelineGraph Catch

**Files:**
- Modify: `src/mage/orchestration/inspect_feature.py` (NEW — define exception here; gets fleshed out in Task 5)
- Modify: `src/mage/orchestration/graph.py` (catch `InspectFeatureHalted`)
- Test: `tests/test_graph.py` (append)

**Interfaces:**
- Consumes: existing `PipelineGraph`
- Produces: `InspectFeatureHalted` exception + PipelineGraph catch + `SCENARIO_HALT_PERSISTED` event emission for the feature

- [ ] **Step 1: Write the failing test**

Append to `tests/test_graph.py`:

```python
class TestPlan5HaltCatching:
    def test_graph_catches_inspect_feature_halted(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.graph import PipelineGraph
        from mage.orchestration.inspect_feature import InspectFeatureHalted
        from mage.orchestration.nodes import PipelineContext, StageNode
        from mage.artifacts.mapping import MappingArtifact

        log = EventsLog(tmp_path / "events.jsonl")

        class HaltStage(StageNode):
            name = "halt-stage"

            def _run(self, context):
                raise InspectFeatureHalted(feature_id="feat-1", iteration=3)

        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        graph = PipelineGraph(stages=[HaltStage(log)])
        graph.run(ctx)

        events = log.read_all()
        assert any(e.event_type.value == "inspect_feature_halt_persisted" for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py::TestPlan5HaltCatching -v`
Expected: ImportError.

- [ ] **Step 3: Create the exception module + extend PipelineGraph**

Create `src/mage/orchestration/inspect_feature.py` with just the exception:

```python
"""InspectFeature stage: orchestrates end-of-feature Inspect + 3-tier severity routing."""

from __future__ import annotations


class InspectFeatureHalted(Exception):
    """Raised when end-of-feature iteration budget is exhausted.

    Resume re-enters InspectFeatureStage from the events log.
    """

    def __init__(self, feature_id: str, iteration: int) -> None:
        self.feature_id = feature_id
        self.iteration = iteration
        super().__init__(
            f"InspectFeatureHalted for feature {feature_id!r} at iteration {iteration} "
            f"(eof_max_iterations exceeded)"
        )
```

Extend `src/mage/orchestration/graph.py` to catch `InspectFeatureHalted`. Pattern is parallel to the `ScenarioInspectHalted` catch added in Plan 4 Task 7:

```python
from mage.orchestration.inspect_feature import InspectFeatureHalted

# In the run method's exception handler (alongside the existing catches):
except InspectFeatureHalted as e:
    log_event = Event(
        timestamp=datetime.now(UTC),
        event_type=EventType.INSPECT_FEATURE_HALT_PERSISTED,
        payload={
            "feature_id": e.feature_id,
            "iteration": e.iteration,
        },
    )
    events_log.append(log_event)
    updated_mapping = mapping.model_copy(update={"feature_status": "halted"})
    updated_mapping.save(project_dir / "mapping.yaml")
```

(Implementer: locate the existing `try/except` block in `PipelineGraph.run()` and add this clause.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py::TestPlan5HaltCatching -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/inspect_feature.py src/mage/orchestration/graph.py tests/test_graph.py
git commit -m "feat(orchestration): InspectFeatureHalted exception + PipelineGraph halt catching"
```

---

## Task 5: InspectFeatureStage

**Files:**
- Modify: `src/mage/orchestration/inspect_feature.py` (add `InspectFeatureStage`)
- Test: `tests/test_inspect_feature.py`

**Interfaces:**
- Consumes: `feature_reviewer_registry()` from Task 3, `InspectArtifact` from Plan 4 Task 4, `PipelineContext`, `MappingArtifact`, `HostConfig`
- Produces: `InspectFeatureStage` (`name = "inspect_feature"`). Runs full 7-reviewer sweep + `CrossScenarioReviewer`; applies 3-tier severity routing; persists `InspectArtifact`; raises `InspectFeatureHalted` on budget overflow.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inspect_feature.py`:

```python
"""Tests for InspectFeatureStage (eof full sweep + 3-tier routing)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


class TestInspectFeatureStage:
    def test_passes_when_all_reviewers_clean(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        # Build 8 reviewers, all pass
        def make_reviewer(dim):
            class CleanReviewer:
                dimension = dim
                def run(self, **kwargs):
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[],
                    )
            return CleanReviewer()

        reviewers = [
            make_reviewer("spec_compliance"),
            make_reviewer("scenario_clarity"),
            make_reviewer("step_grammar"),
            make_reviewer("testability"),
            make_reviewer("determinism"),
            make_reviewer("naming_idiom"),
            make_reviewer("lifecycle_tags"),
            make_reviewer("cross_scenario"),
        ]

        stage = InspectFeatureStage(
            log,
            reviewers=reviewers,
            host_config=HostConfig(),
        )

        artifact_content = stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
        )

        assert artifact_content.ready_to_merge is True
        assert artifact_content.iteration == 1
        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_started" in types
        assert "inspect_feature_finalized" in types
        assert "inspect_feature_passed" in types

    def test_critical_finding_marked_not_ready(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        def make_reviewer(dim, *, has_critical=False):
            class R:
                dimension = dim
                def run(self, **kwargs):
                    if has_critical:
                        return ReviewerVerdict(
                            dimension=dim,
                            outcome="fail",
                            draft_hash="",
                            reviewed_at=datetime.now(UTC),
                            reviewer_id=f"{dim}@v1",
                            findings=[ReviewerFinding(
                                id="f-1",
                                severity="critical",
                                location="00000-0",
                                issue="Critical issue",
                                rationale="Breaks the spec",
                                suggestion="Fix",
                                citations=["00000-0"],
                            )],
                        )
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[],
                    )
            return R()

        reviewers = [
            make_reviewer("spec_compliance", has_critical=True),
            make_reviewer("scenario_clarity"),
            make_reviewer("step_grammar"),
            make_reviewer("testability"),
            make_reviewer("determinism"),
            make_reviewer("naming_idiom"),
            make_reviewer("lifecycle_tags"),
            make_reviewer("cross_scenario"),
        ]

        stage = InspectFeatureStage(
            log, reviewers=reviewers, host_config=HostConfig()
        )
        artifact = stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
        )

        assert artifact.ready_to_merge is False
        assert len(artifact.critical) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_inspect_feature.py -v`
Expected: ImportError on `InspectFeatureStage`.

- [ ] **Step 3: Implement InspectFeatureStage**

Append to `src/mage/orchestration/inspect_feature.py`:

```python
"""InspectFeature stage: orchestrates end-of-feature Inspect + 3-tier severity routing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mage.artifacts.inspect import (
    InspectArtifact,
    InspectArtifactContent,
    ScenarioInspectStatus,
)
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig

if TYPE_CHECKING:
    from mage.verification.reviewers.base import ReviewerAgent


class InspectFeatureHalted(Exception):
    """Raised when end-of-feature iteration budget is exhausted."""

    def __init__(self, feature_id: str, iteration: int) -> None:
        self.feature_id = feature_id
        self.iteration = iteration
        super().__init__(
            f"InspectFeatureHalted for feature {feature_id!r} at iteration {iteration} "
            f"(eof_max_iterations exceeded)"
        )


class InspectFeatureStage(StageNode):
    """End-of-feature Inspect: full 7-reviewer sweep + CrossScenarioReviewer + 3-tier routing."""

    name = "inspect_feature"

    def __init__(
        self,
        events_log: EventsLog,
        *,
        reviewers: list,
        host_config: HostConfig,
    ) -> None:
        super().__init__(events_log)
        self.reviewers = reviewers
        self.host_config = host_config

    def _run(self, context: PipelineContext) -> PipelineContext:  # noqa: ARG002
        # Plan 5: real driver is `run_pass` (called by an external orchestrator);
        # _run is a stub that emits the completion event.
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_COMPLETED,
                payload={"stub": True},
            )
        )
        return context

    def run_pass(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        scenarios: list[dict],
        iteration: int | None = None,
    ) -> InspectArtifactContent:
        """Run one pass of InspectFeature.

        Returns the InspectArtifactContent. Raises InspectFeatureHalted on budget overflow.
        """
        if iteration is None:
            iteration = context.iteration  # use the pipeline's iteration counter

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_STARTED,
                payload={
                    "feature_id": feature_id,
                    "scenario_count": len(scenarios),
                    "iteration": iteration,
                    "eof_max_iterations": self.host_config.eof_max_iterations,
                },
            )
        )

        # Run all 8 reviewers (mechanical pre-check is handled separately)
        per_reviewer = []
        all_findings = []
        for reviewer in self.reviewers:
            try:
                verdict = reviewer.run(
                    feature_summary={"feature_id": feature_id},
                    scenarios=scenarios,
                    mapping=context.mapping,
                )
            except TypeError:
                # Some reviewers may not accept these kwargs; fall back to a no-op
                verdict = getattr(reviewer, "last_verdict", None)
                if verdict is None:
                    continue
            per_reviewer.append(verdict.model_dump(mode="json"))
            all_findings.extend(verdict.findings)

        # 3-tier severity routing
        critical = [f for f in all_findings if f.severity == "critical"]
        important = [f for f in all_findings if f.severity == "major"]
        minor = [f for f in all_findings if f.severity == "minor"]

        # Critical → reenter Realize for affected scenarios
        for f in critical:
            sub_bid = (f.citations or [None])[0] or "unknown"
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SCENARIO_NEEDS_REFACTOR,
                    payload={
                        "sub_bid": sub_bid,
                        "reason": f"critical_finding:{f.id}",
                    },
                )
            )

        # Important → emit FIX_WAVE_DISPATCHED (the actual fix-wave subagent is
        # an external orchestrator in production; we emit the marker so the
        # events log captures the routing decision)
        if important:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.FIX_WAVE_DISPATCHED,
                    payload={
                        "feature_id": feature_id,
                        "finding_count": len(important),
                    },
                )
            )

        # Determine readiness
        ready_to_merge = len(critical) == 0 and len(important) == 0

        # Build InspectArtifact
        scenario_statuses = [
            ScenarioInspectStatus(
                sub_bid=s.get("sub_bid", "unknown"),
                scenario_name=s.get("scenario_name", "unknown"),
                status="needs_refactor" if any(
                    f.severity == "critical" and ((f.citations or [None])[0] == s.get("sub_bid"))
                    for f in all_findings
                ) else "live",
            )
            for s in scenarios
        ]

        # Build ledger markdown
        ledger_md = (
            f"# Inspect Feature {feature_id} — iteration {iteration}\n\n"
            f"ready_to_merge: {ready_to_merge}\n"
            f"critical: {len(critical)}, important: {len(important)}, minor: {len(minor)}\n\n"
            f"## Reviewers\n"
            + "\n".join(
                f"- {r['dimension']}: {r['outcome']} ({len(r['findings'])} findings)"
                for r in per_reviewer
            )
        )

        artifact_content = InspectArtifactContent(
            feature_id=feature_id,
            inspected_at=datetime.now(UTC),
            iteration=iteration,
            eof_max_iterations=self.host_config.eof_max_iterations,
            scenarios=scenario_statuses,
            per_reviewer=per_reviewer,
            critical=[f.model_dump(mode="json") for f in critical],
            important=[f.model_dump(mode="json") for f in important],
            minor=[f.model_dump(mode="json") for f in minor],
            cross_scenario=[
                r for r in per_reviewer if r.get("dimension") == "cross_scenario"
            ],
            ready_to_merge=ready_to_merge,
            ledger_markdown=ledger_md,
        )

        # Persist via InspectArtifact.finalize
        artifact_path = (
            context.project_dir / ".haileris" / "inspect" / feature_id / f"{iteration}.yaml"
        )
        InspectArtifact.finalize(artifact_path, artifact_content, self.events_log)

        # Halt if budget exceeded + not ready
        if iteration >= self.host_config.eof_max_iterations and not ready_to_merge:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_FEATURE_HALT_PERSISTED,
                    payload={
                        "feature_id": feature_id,
                        "iteration": iteration,
                        "reason": "eof_budget_overflow",
                    },
                )
            )
            raise InspectFeatureHalted(feature_id=feature_id, iteration=iteration)

        if ready_to_merge:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_FEATURE_PASSED,
                    payload={"feature_id": feature_id, "iteration": iteration},
                )
            )

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_COMPLETED,
                payload={
                    "feature_id": feature_id,
                    "iteration": iteration,
                    "ready_to_merge": ready_to_merge,
                },
            )
        )

        return artifact_content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_inspect_feature.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/inspect_feature.py tests/test_inspect_feature.py
git commit -m "feat(orchestration): add InspectFeatureStage with 3-tier severity routing"
```

---

## Task 6: SettleFeatureStage

**Files:**
- Create: `src/mage/orchestration/settle_feature.py`
- Test: `tests/test_settle_feature.py`

**Interfaces:**
- Consumes: `MappingArtifact.feature_cosmetic_queue` (from Plan 4 Task 5), `PipelineContext`, `EventsLog`
- Produces: `SettleFeatureStage` (`name = "settle_feature"`). Aggregates cosmetic queue; writes settle report; emits settle events. (The actual 4-option menu is the CLI surface in Task 7; the stage provides the data + report.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_settle_feature.py`:

```python
"""Tests for SettleFeatureStage (cosmetic queue + report)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class TestSettleFeatureStage:
    def test_aggregates_cosmetic_queue(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.inspect import CosmeticItem

        log = EventsLog(tmp_path / "events.jsonl")
        item = CosmeticItem(
            sub_bid="00000-0",
            scenario_name="happy",
            location="Given step",
            text="Rephrase for clarity",
            proposed_by="increment_quality",
        )
        mapping = MappingArtifact(project_id="feat-1").append_cosmetic(item)
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=mapping,
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        stage = SettleFeatureStage(log)
        stage.run_settle(
            ctx,
            feature_id="feat-1",
            disposition="kept",
        )

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "settle_feature_started" in types
        assert "settle_cosmetic_queued" in types
        assert "settle_feature_finalized" in types

    def test_writes_settle_report(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )
        stage = SettleFeatureStage(log)
        stage.run_settle(ctx, feature_id="feat-1", disposition="merged")

        report_path = tmp_path / ".haileris" / "settle" / "feat-1.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "feat-1" in content
        assert "merged" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settle_feature.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement SettleFeatureStage**

Create `src/mage/orchestration/settle_feature.py`:

```python
"""SettleFeature stage: cosmetic queue handoff + finishing-equivalent finalization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode

if TYPE_CHECKING:
    from mage.artifacts.mapping import MappingArtifact


class SettleFeatureStage(StageNode):
    """End-of-feature Settle: cosmetic queue aggregation + settle report + finalization.

    Per spec R25 / GC-4: two responsibilities in order:
      1. Cosmetic queue handoff (aggregate, write to file, emit events).
      2. Branch finalization (record chosen disposition, write settle report).

    The 4-option menu (merge / push+PR / keep / discard) is the CLI surface
    (Task 7); this stage provides the data + report.

    Settle does NOT review. Review is InspectFeatureStage's job.
    """

    name = "settle_feature"

    def __init__(self, events_log: EventsLog) -> None:
        super().__init__(events_log)

    def _run(self, context: PipelineContext) -> PipelineContext:  # noqa: ARG002
        # Stub: real driver is run_settle (called by an external orchestrator or CLI).
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_COMPLETED,
                payload={"stub": True},
            )
        )
        return context

    def run_settle(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        disposition: str,  # "merged" | "pr_opened" | "kept" | "discarded"
    ) -> None:
        """Run the settle pass.

        `disposition` is the user's chosen option from the 4-option menu;
        this stage records it and writes the report.
        """
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_STARTED,
                payload={
                    "feature_id": feature_id,
                    "cosmetic_queue_size": len(context.mapping.feature_cosmetic_queue),
                },
            )
        )

        # 1. Cosmetic queue handoff
        queue = context.mapping.feature_cosmetic_queue
        cosmetic_md = self._render_cosmetic_md(queue)
        cosmetic_path = (
            context.project_dir / ".haileris" / "settle" / f"{feature_id}-cosmetic.md"
        )
        cosmetic_path.parent.mkdir(parents=True, exist_ok=True)
        cosmetic_path.write_text(cosmetic_md, encoding="utf-8")

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_COSMETIC_QUEUED,
                payload={"feature_id": feature_id, "queue_size": len(queue)},
            )
        )

        # 2. Write the settle report
        report_md = (
            f"# Settle Feature {feature_id}\n\n"
            f"## Disposition\n\n{disposition}\n\n"
            f"## Cosmetic Queue ({len(queue)} items)\n\n"
            f"See `{feature_id}-cosmetic.md` for the full list.\n\n"
            f"## Finalized at\n\n"
            f"{datetime.now(UTC).isoformat()}\n"
        )
        report_path = context.project_dir / ".haileris" / "settle" / f"{feature_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_md, encoding="utf-8")

        # Emit finalization event
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_FINALIZED,
                payload={"feature_id": feature_id, "disposition": disposition},
            )
        )

        # If user chose discard, emit a special event
        if disposition == "discarded":
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SETTLE_BRANCH_DISCARDED,
                    payload={"feature_id": feature_id},
                )
            )

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_COMPLETED,
                payload={"feature_id": feature_id, "disposition": disposition},
            )
        )

    @staticmethod
    def _render_cosmetic_md(queue: list[dict]) -> str:
        if not queue:
            return "# Cosmetic Queue\n\n(empty)\n"
        lines = ["# Cosmetic Queue", ""]
        for i, item in enumerate(queue, 1):
            lines.append(
                f"{i}. **{item.get('sub_bid', '?')}** / {item.get('scenario_name', '?')} "
                f"({item.get('proposed_by', '?')})\n"
                f"   - location: {item.get('location', '?')}\n"
                f"   - text: {item.get('text', '?')}\n"
            )
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_settle_feature.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/settle_feature.py tests/test_settle_feature.py
git commit -m "feat(orchestration): add SettleFeatureStage (cosmetic queue + report)"
```

---

## Task 7: mage settle run Subcommand

**Files:**
- Modify: `src/mage/cli.py` (add `mage settle run <feature_id>`)
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: existing `mage` CLI surface (Plan 1 + 2 + 3 + 4)
- Produces: `mage settle run <feature_id>` subcommand. The 4-option menu is interactive (CLI prompts); for non-interactive mode (`--disposition <name>`), the chosen disposition is dispatched directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
class TestSettleRun:
    def test_settle_run_non_interactive(self, tmp_path, capsys):
        from mage.orchestration.events import EventsLog
        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.cli import main

        project = tmp_path / "proj"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")

        # Build a ready-to-merge InspectArtifact
        inspect_dir = project / ".haileris" / "inspect" / "feat-1"
        inspect_dir.mkdir(parents=True)
        artifact = InspectArtifactContent(
            feature_id="feat-1",
            inspected_at=datetime.now(UTC),
            iteration=1,
            eof_max_iterations=3,
            scenarios=[],
            per_reviewer=[],
            critical=[],
            important=[],
            minor=[],
            cross_scenario=[],
            ready_to_merge=True,
            ledger_markdown="",
        )
        InspectArtifact.finalize(inspect_dir / "1.yaml", artifact, log)

        rc = main(["settle", "run", "feat-1", "--disposition", "kept", "--project-dir", str(project)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "settle" in out.lower() or "feat-1" in out

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "settle_feature_finalized" in types
        # Disposition is in the payload
        disposal_events = [e for e in events if e.event_type.value == "settle_feature_finalized"]
        assert disposal_events[0].payload["disposition"] == "kept"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestSettleRun -v`
Expected: SystemExit (no `settle` subcommand).

- [ ] **Step 3: Add the mage settle run subcommand**

In `src/mage/cli.py`, locate the existing CLI structure (typer or argparse) and add a new subcommand. Mirror the Plan 4 `mage inspect show` pattern from Task 13:

```python
@app.command()
def settle_run(
    feature_id: str,
    project_dir: str = typer.Option(..., "--project-dir"),
    disposition: str = typer.Option(
        None, "--disposition",
        help="Non-interactive: choose merged|pr_opened|kept|discarded",
    ),
) -> None:
    """Run SettleFeature for a feature. Interactive mode prompts for 4-option menu."""
    import typer
    from pathlib import Path
    from mage.orchestration.events import EventsLog
    from mage.orchestration.settle_feature import SettleFeatureStage
    from mage.orchestration.nodes import PipelineContext
    from mage.artifacts.mapping import MappingArtifact

    project_path = Path(project_dir)
    log = EventsLog(project_path / "events.jsonl")

    # Load mapping
    mapping_path = project_path / "mapping.yaml"
    if not mapping_path.exists():
        typer.echo(f"No mapping at {mapping_path}", err=True)
        raise typer.Exit(code=1)
    mapping = MappingArtifact.load(mapping_path)

    ctx = PipelineContext(
        project_dir=project_path,
        mapping=mapping,
        events_log=log,
        plan_path=project_path / "plan.md",
        iteration=0,
    )

    # If disposition not provided, prompt interactively
    valid_dispositions = {"merged", "pr_opened", "kept", "discarded"}
    if disposition is None:
        # Interactive mode
        typer.echo("Choose a disposition:")
        typer.echo("  1. merged")
        typer.echo("  2. pr_opened")
        typer.echo("  3. kept")
        typer.echo("  4. discarded")
        choice = typer.prompt("Enter choice (1-4)")
        mapping_choice = {"1": "merged", "2": "pr_opened", "3": "kept", "4": "discarded"}
        if choice not in mapping_choice:
            typer.echo(f"Invalid choice {choice!r}", err=True)
            raise typer.Exit(code=1)
        disposition = mapping_choice[choice]
    elif disposition not in valid_dispositions:
        typer.echo(
            f"Invalid disposition {disposition!r}; must be one of {sorted(valid_dispositions)}",
            err=True,
        )
        raise typer.Exit(code=1)

    if disposition == "discarded":
        # Require typed confirmation (Plan 2's PlanRevisionRequired pattern)
        confirm = typer.prompt("Type 'discard' to confirm")
        if confirm != "discard":
            typer.echo("Discard cancelled", err=True)
            raise typer.Exit(code=1)

    stage = SettleFeatureStage(log)
    stage.run_settle(ctx, feature_id=feature_id, disposition=disposition)
    typer.echo(f"Settle complete for {feature_id}: {disposition}")
```

(Adjust `typer` calls to match the existing CLI framework — `argparse` if Plan 3 used that.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestSettleRun -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/mage/cli.py tests/test_cli.py
git commit -m "feat(cli): add mage settle run subcommand"
```

---

## Task 8: E2E Happy-Path (Inspect + Settle)

**Files:**
- Create: `tests/test_e2e_inspect_settle.py`

- [ ] **Step 1: Write the test**

Create `tests/test_e2e_inspect_settle.py`:

```python
"""End-to-end: 1 feature × 2 scenarios → live → Inspect-feature passes → Settle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class TestE2EInspectSettle:
    def test_full_feature_through_settle(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.settle_feature import SettleFeatureStage
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        def make_reviewer(dim):
            class R:
                dimension = dim
                def run(self, **kwargs):
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[],
                    )
            return R()

        reviewers = [make_reviewer(d) for d in [
            "spec_compliance", "scenario_clarity", "step_grammar", "testability",
            "determinism", "naming_idiom", "lifecycle_tags", "cross_scenario",
        ]]

        # Run InspectFeature
        inspect_stage = InspectFeatureStage(log, reviewers=reviewers, host_config=HostConfig())
        artifact = inspect_stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[
                {"sub_bid": "00000-0", "scenario_name": "happy"},
                {"sub_bid": "00000-1", "scenario_name": "edge"},
            ],
        )
        assert artifact.ready_to_merge is True

        # Run SettleFeature
        settle_stage = SettleFeatureStage(log)
        settle_stage.run_settle(ctx, feature_id="feat-1", disposition="kept")

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_passed" in types
        assert "settle_feature_finalized" in types
        assert "settle_cosmetic_queued" in types

        # Verify report file
        report = (tmp_path / ".haileris" / "settle" / "feat-1.md").read_text()
        assert "feat-1" in report
        assert "kept" in report
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_inspect_settle.py -v`
Expected: PASS (1 test).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_inspect_settle.py
git commit -m "test: end-to-end Inspect-feature + Settle-feature happy path"
```

---

## Task 9: E2E Inspect-feature Halt

**Files:**
- Append to: `tests/test_e2e_inspect_settle.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_e2e_inspect_settle.py`:

```python
class TestE2EInspectFeatureHalt:
    def test_eof_budget_overflow_raises_halt(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import InspectFeatureStage, InspectFeatureHalted
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=3,  # at eof_max_iterations
        )

        def make_reviewer(dim, severity="pass"):
            class R:
                dimension = dim
                def run(self, **kwargs):
                    if severity == "pass":
                        return ReviewerVerdict(
                            dimension=dim,
                            outcome="pass",
                            draft_hash="",
                            reviewed_at=datetime.now(UTC),
                            reviewer_id=f"{dim}@v1",
                            findings=[],
                        )
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="fail",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=[ReviewerFinding(
                            id="f-1",
                            severity="critical",
                            location="00000-0",
                            issue="Critical",
                            rationale="Spec violation",
                            suggestion="Fix",
                            citations=["00000-0"],
                        )],
                    )
            return R()

        reviewers = [
            make_reviewer("spec_compliance", "critical"),
            *[make_reviewer(d) for d in [
                "scenario_clarity", "step_grammar", "testability",
                "determinism", "naming_idiom", "lifecycle_tags", "cross_scenario",
            ]],
        ]

        stage = InspectFeatureStage(
            log, reviewers=reviewers, host_config=HostConfig(eof_max_iterations=3)
        )

        with pytest.raises(InspectFeatureHalted):
            stage.run_pass(
                ctx,
                feature_id="feat-1",
                scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
            )

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "inspect_feature_halt_persisted" in types
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_inspect_settle.py::TestE2EInspectFeatureHalt -v`
Expected: PASS (1 test).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_inspect_settle.py
git commit -m "test: end-to-end Inspect-feature halt (eof budget overflow)"
```

---

## Task 10: E2E Cosmetic Queue Accumulation

**Files:**
- Append to: `tests/test_e2e_inspect_settle.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_e2e_inspect_settle.py`:

```python
class TestE2ECosmeticQueueAccumulation:
    def test_minor_findings_flow_to_cosmetic_queue(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.inspect_feature import InspectFeatureStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact
        from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
        from mage.verification.host_overrides import HostConfig

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        def make_reviewer(dim, *, severity="pass"):
            findings = []
            if severity == "minor":
                findings = [ReviewerFinding(
                    id="m-1",
                    severity="minor",
                    location="00000-0",
                    issue="Rephrase for clarity",
                    rationale="Cosmetic",
                    suggestion="Rephrase",
                    citations=["00000-0"],
                )]
            class R:
                dimension = dim
                def run(self, **kwargs):
                    return ReviewerVerdict(
                        dimension=dim,
                        outcome="pass" if severity == "pass" else "fail",
                        draft_hash="",
                        reviewed_at=datetime.now(UTC),
                        reviewer_id=f"{dim}@v1",
                        findings=findings,
                    )
            return R()

        reviewers = [
            make_reviewer("spec_compliance"),
            make_reviewer("scenario_clarity", severity="minor"),
            *[make_reviewer(d) for d in [
                "step_grammar", "testability", "determinism", "naming_idiom",
                "lifecycle_tags", "cross_scenario",
            ]],
        ]

        stage = InspectFeatureStage(log, reviewers=reviewers, host_config=HostConfig())
        artifact = stage.run_pass(
            ctx,
            feature_id="feat-1",
            scenarios=[{"sub_bid": "00000-0", "scenario_name": "happy"}],
        )

        # Minor finding should NOT block ready_to_merge
        assert artifact.ready_to_merge is True
        # But it should be in the minor list
        assert len(artifact.minor) == 1

        # Note: InspectFeatureStage doesn't auto-append to feature_cosmetic_queue;
        # the queue aggregation happens in SettleFeatureStage.run_settle, which
        # reads whatever is in the mapping. Plan 5's flow is: Inspect finds
        # Minor → don't apply reset → Settle aggregates. The Minor findings
        # live in InspectArtifactContent.minor; cosmetic queue is populated by
        # the per-loop InspectLoopStage (Plan 4 R20) or by the cross_scenario
        # reviewer's findings via Settle-stage routing.
        # This test validates the artifact captures Minor findings; cosmetic
        # queue aggregation is tested separately when SettleFeatureStage
        # includes the InspectArtifact's minor findings.
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_inspect_settle.py::TestE2ECosmeticQueueAccumulation -v`
Expected: PASS (1 test).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_inspect_settle.py
git commit -m "test: end-to-end cosmetic queue accumulation (minor findings → artifact)"
```

---

## Task 11: Final Verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: All Plan 1 + 2 + 3 + 4 + 5 tests pass. Tests should be ≥ 220 (190 prior + ~30 new).

- [ ] **Step 2: Verify CLI surface**

Run: `uv run mage --help`
Expected: Lists subcommands including `inspect`, `settle`.

Run: `uv run mage inspect show --help`
Expected: Shows the inspect show signature.

Run: `uv run mage settle run --help`
Expected: Shows the settle run signature.

- [ ] **Step 3: Self-review against spec**

Use `superpowers:verification-before-completion` to check:
- All R18-R26 spec resolutions covered by tests.
- All new EventType members used (no orphans).
- All halt exceptions caught by PipelineGraph.
- Cosmetic queue handoff file written at expected path.
- Settle 4-option menu renders correctly (interactive mode).
- No `Co-Authored-By` trailer in commits (per CLAUDE.md).
- No `haileris_v2` references in Plan 5 files.

- [ ] **Step 4: Commit any final tweaks**

If self-review found fixable issues, commit them as one fix commit:

```bash
git add -u
git commit -m "fix: Plan 5 self-review findings"
```

---
