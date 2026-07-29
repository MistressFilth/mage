# Three Practices Discipline Enforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the Three Practices (Discovery → Formulation → Automation) and their recurrence rules (revision, supersession) as a first-class pipeline concern, with full audit trail in the mapping artifact.

**Architecture:** One `DisciplineStage` (Pydantic-Graph node) subscribed to stage events. A pure `src/mage/orchestration/discipline/policy.py` module holds the six Approved Gate Scope rules from parent v2 design plus revision and supersession flows. Stage calls policy methods; policy writes audit entries to `BaseBIDEntry.reversion_log` and `BaseBIDEntry.post_live_revisions`.

**Tech Stack:** Pydantic-Graph, Pydantic models, existing `MappingArtifact` / `BaseBIDEntry` / `ScenarioEntry` schemas, existing `EventType` enum extended with four new members, existing `PipelineContext` already has `current_sub_bid` field (no change).

## Global Constraints

- The string `haileris_v2` is forbidden anywhere in the tree (AGENTS.md).
- Commits follow Conventional Commits. No `Co-Authored-By` trailers (CLAUDE.md).
- Events are the audit trail. Any new stage outcome gets an `EventType` member and an emitted `Event` (AGENTS.md).
- Nothing shells out directly. Stages take an injected `command_runner`; tests substitute a recording fake (AGENTS.md).
- `MappingArtifact`, `BaseBIDEntry`, `ScenarioEntry` schemas unchanged. Plan 7 wires writers, not new fields (verified against `src/mage/artifacts/mapping.py`).
- `PipelineContext.current_sub_bid` field already exists from Plan 6 (`src/mage/orchestration/nodes.py:26`). Plan 7 reuses it for cycle lock — no field addition.
- Six Approved Gate Scope rules from parent v2 design are pinned. Recurrence types (revision, full supersession) pinned. Partial supersession is out of scope.
- All existing tests must remain green (334 baseline).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/mage/orchestration/exceptions.py` | Create | `DisciplineViolation` base + 5 subclasses |
| `src/mage/orchestration/events.py` | Modify | Add 4 new `EventType` members |
| `src/mage/orchestration/discipline/__init__.py` | Create | Package marker, re-export `Policy`, `DisciplineStage` |
| `src/mage/orchestration/discipline/policy.py` | Create | Pure functions for the six rules + revision + supersession + cosmetic guard |
| `src/mage/orchestration/discipline/stage.py` | Create | `DisciplineStage` (Pydantic-Graph node) |
| `src/mage/orchestration/automation.py` | Modify | Add `guard_automation_entry` call before dispatching Etch |
| `src/mage/orchestration/inscribe.py` | Modify | Acquire cycle lock at sub-phase entry, emit `SCENARIO_REVISION_REQUESTED` on spec-route finding |
| `src/mage/orchestration/settle_feature.py` | Modify | Emit `SCENARIO_SUPERSESSION_REQUESTED` on supersession trigger |
| `tests/unit/test_discipline_policy.py` | Create | 26 unit tests for `Policy` |
| `tests/unit/test_discipline_stage.py` | Create | 7 unit tests for `DisciplineStage` |
| `tests/features/test_e2e_three_practices.py` | Create | 5 e2e tests for revision/supersession/cosmetic/plans |

---

## Task Structure

### Task 1: Discipline exception module

**Files:**
- Create: `src/mage/orchestration/exceptions.py`

**Interfaces:**
- Consumes: nothing
- Produces: `DisciplineViolation`, `ForwardOrderViolation`, `CycleAlreadyInProgress`, `NotApprovedForAutomation`, `DecompositionOpen`, `ModelCannotApplyCosmetic`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_discipline_exceptions.py
from mage.orchestration.exceptions import (
    DisciplineViolation,
    ForwardOrderViolation,
    CycleAlreadyInProgress,
    NotApprovedForAutomation,
    DecompositionOpen,
    ModelCannotApplyCosmetic,
)


def test_all_subclass_discipline_violation():
    for cls in (
        ForwardOrderViolation,
        CycleAlreadyInProgress,
        NotApprovedForAutomation,
        DecompositionOpen,
        ModelCannotApplyCosmetic,
    ):
        assert issubclass(cls, DisciplineViolation)


def test_subclasses_carry_message():
    err = ForwardOrderViolation("scenario 1 still inscribing")
    assert isinstance(err, DisciplineViolation)
    assert "still inscribing" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_exceptions.py -v`
Expected: FAIL with `ModuleNotFoundError: mage.orchestration.exceptions`

- [ ] **Step 3: Create the module**

```python
# src/mage/orchestration/exceptions.py
"""Discipline enforcement exception hierarchy.

All Three Practices gate failures raise subclasses of DisciplineViolation.
Distinguishing the failure type lets DisciplineStage emit a precise event
instead of a generic halt.
"""

from __future__ import annotations


class DisciplineViolation(Exception):
    """Base for all Three Practices gate failures."""


class ForwardOrderViolation(DisciplineViolation):
    """P1 / P3 / P4: scenario attempted to start before its predecessor completed."""


class CycleAlreadyInProgress(DisciplineViolation):
    """P2: another scenario's cycle already holds the cycle lock."""


class NotApprovedForAutomation(DisciplineViolation):
    """P3: scenario attempted Etch/Realize entry without APPROVED status."""


class DecompositionOpen(DisciplineViolation):
    """P4: per-scenario cycle started before Decomposition closed."""


class ModelCannotApplyCosmetic(DisciplineViolation):
    """Cosmetic gate: model attempted to apply a live-scenario text change."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_exceptions.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/exceptions.py tests/unit/test_discipline_exceptions.py
git commit -m "feat(discipline): add exception hierarchy for gate failures"
```

---

### Task 2: New EventType members

**Files:**
- Modify: `src/mage/orchestration/events.py:95` (append after line 94)

**Interfaces:**
- Consumes: existing `EventType` enum
- Produces: `SCENARIO_REVERTED_TO_INSCRIBING`, `SCENARIO_REVISION_REQUESTED`, `SCENARIO_SUPERSESSION_REQUESTED`, `SCENARIO_DEPRECATED`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_event_type_members.py
from mage.orchestration.events import EventType


def test_plan7_event_type_members_exist():
    for name in (
        "SCENARIO_REVERTED_TO_INSCRIBING",
        "SCENARIO_REVISION_REQUESTED",
        "SCENARIO_SUPERSESSION_REQUESTED",
        "SCENARIO_DEPRECATED",
    ):
        assert hasattr(EventType, name), f"EventType.{name} missing"


def test_event_type_values_unique():
    values = [m.value for m in EventType]
    assert len(values) == len(set(values)), "duplicate EventType values"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_event_type_members.py -v`
Expected: FAIL with `AssertionError: EventType.SCENARIO_REVERTED_TO_INSCRIBING missing`

- [ ] **Step 3: Append the new members**

Edit `src/mage/orchestration/events.py` — after the existing `SETTLE_CLEANUP_SKIPPED` line, add:

```python

    # Plan 7 — Discipline enforcement
    SCENARIO_REVERTED_TO_INSCRIBING = "scenario_reverted_to_inscribing"
    SCENARIO_REVISION_REQUESTED = "scenario_revision_requested"
    SCENARIO_SUPERSESSION_REQUESTED = "scenario_supersession_requested"
    SCENARIO_DEPRECATED = "scenario_deprecated"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_event_type_members.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/events.py tests/unit/test_event_type_members.py
git commit -m "feat(events): add four Plan 7 discipline event types"
```

---

### Task 3: Discipline package init + base structure

**Files:**
- Create: `src/mage/orchestration/discipline/__init__.py`

- [ ] **Step 1: Create the package directory and init**

```python
# src/mage/orchestration/discipline/__init__.py
"""Three Practices discipline enforcement.

Package contents:
- policy: pure functions for the six Approved Gate Scope rules + revision +
  supersession + cosmetic guard.
- stage: DisciplineStage (Pydantic-Graph node) that wires policy into the
  event stream.
"""

from __future__ import annotations
```

- [ ] **Step 2: Commit**

```bash
git add src/mage/orchestration/discipline/__init__.py
git commit -m "feat(discipline): add package init"
```

---

### Task 4: Policy P1 — per-scenario independence

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py` (new)
- Test: `tests/unit/test_discipline_policy.py` (new)

**Interfaces:**
- Consumes: `MappingArtifact`, target `sub_bid` string
- Produces: `assert_independent_gates(mapping, sub_bid) -> None`; raises `ForwardOrderViolation`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_discipline_policy.py — P1 section
from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.discipline.policy import assert_independent_gates
from mage.orchestration.exceptions import ForwardOrderViolation
import pytest


def _scenario(sub_bid: str, status: LifecycleStatus) -> ScenarioEntry:
    return ScenarioEntry(sub_bid=sub_bid, scenario_text_hash="h", lifecycle_status=status)


def _mapping(scenarios: list[ScenarioEntry]) -> MappingArtifact:
    return MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b",
                behavior_description="d",
                scenarios=scenarios,
            )
        ],
    )


def test_p1_passes_when_earlier_live():
    m = _mapping([_scenario("A", LifecycleStatus.LIVE), _scenario("B", LifecycleStatus.INSCRIBING)])
    assert_independent_gates(m, "B")  # no raise


def test_p1_passes_when_earlier_deprecated():
    m = _mapping([_scenario("A", LifecycleStatus.DEPRECATED), _scenario("B", LifecycleStatus.INSCRIBING)])
    assert_independent_gates(m, "B")  # no raise


def test_p1_raises_when_earlier_inscribing():
    m = _mapping([_scenario("A", LifecycleStatus.INSCRIBING), _scenario("B", LifecycleStatus.INSCRIBING)])
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")


def test_p1_raises_when_earlier_approved():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED), _scenario("B", LifecycleStatus.INSCRIBING)])
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")


def test_p1_respects_base_bid_ordering():
    # Scenario "B" in base_bid 00000 declared after "A" in 00001; A must be live first.
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                         scenarios=[_scenario("A", LifecycleStatus.INSCRIBING)]),
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("B", LifecycleStatus.INSCRIBING)]),
        ],
    )
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: mage.orchestration.discipline.policy`

- [ ] **Step 3: Create policy module with P1**

```python
# src/mage/orchestration/discipline/policy.py
"""Pure functions implementing the Three Practices Approved Gate Scope rules.

Six rules (P1-P6) from parent v2 design lines 291-305. Each function is
side-effect-free except for raising exceptions and returning updated Pydantic
models via model_copy.
"""

from __future__ import annotations

from datetime import datetime

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    PostLiveRevisionEntry,
    ReversionLogEntry,
    ScenarioEntry,
)
from mage.orchestration.exceptions import (
    DecompositionOpen,
    ForwardOrderViolation,
    ModelCannotApplyCosmetic,
    NotApprovedForAutomation,
)
from mage.orchestration.events import EventsLog
from mage.artifacts.plan import PlanArtifact, PlanNotFinalizedError


# Statuses that satisfy "predecessor finished" for build-order enforcement.
_PREDECESSOR_DONE_STATUSES = frozenset({
    LifecycleStatus.LIVE,
    LifecycleStatus.DEPRECATED,
    LifecycleStatus.RETIRED,
})


def _all_scenarios(mapping: MappingArtifact) -> list[ScenarioEntry]:
    """Flatten scenarios across base_bids in declared order."""
    out: list[ScenarioEntry] = []
    for entry in mapping.base_bids:
        out.extend(entry.scenarios)
    return out


def _find_entry_for_sub_bid(
    mapping: MappingArtifact, sub_bid: str
) -> tuple[BaseBIDEntry, int]:
    """Return (entry, scenario_index) for the given sub_bid. Raise if absent."""
    for entry in mapping.base_bids:
        for idx, scenario in enumerate(entry.scenarios):
            if scenario.sub_bid == sub_bid:
                return entry, idx
    raise ForwardOrderViolation(f"sub_bid {sub_bid!r} not found in mapping")


# P1 — Per-scenario independence
def assert_independent_gates(mapping: MappingArtifact, sub_bid: str) -> None:
    """Scenario `sub_bid` may start only if every earlier scenario is done."""
    all_scenarios = _all_scenarios(mapping)
    target_index = next(
        (i for i, s in enumerate(all_scenarios) if s.sub_bid == sub_bid),
        None,
    )
    if target_index is None:
        raise ForwardOrderViolation(f"sub_bid {sub_bid!r} not found in mapping")
    for earlier in all_scenarios[:target_index]:
        if earlier.lifecycle_status not in _PREDECESSOR_DONE_STATUSES:
            raise ForwardOrderViolation(
                f"sub_bid {sub_bid!r} cannot start: earlier scenario "
                f"{earlier.sub_bid!r} has status {earlier.lifecycle_status.value!r}; "
                f"expected one of {sorted(s.value for s in _PREDECESSOR_DONE_STATUSES)}"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p1"`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add P1 per-scenario independence rule"
```

---

### Task 5: Policy P2 — sequential cycle lock

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py`
- Modify: `tests/unit/test_discipline_policy.py`

**Interfaces:**
- Produces: `acquire_cycle_lock(context, sub_bid) -> None`; `release_cycle_lock(context) -> None`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_discipline_policy.py`:

```python
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.discipline.policy import (
    acquire_cycle_lock,
    release_cycle_lock,
)
from mage.orchestration.exceptions import CycleAlreadyInProgress
import tempfile
from pathlib import Path


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=_mapping([]),
        events_log=__import__("mage.orchestration.events", fromlist=["EventsLog"]).EventsLog(tmp_path / "events.jsonl"),
    )


def test_p2_acquire_succeeds_when_unset(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    assert ctx.current_sub_bid == "A"


def test_p2_acquire_raises_when_held_by_other(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    with pytest.raises(CycleAlreadyInProgress):
        acquire_cycle_lock(ctx, "B")


def test_p2_acquire_allows_same_sub_bid_reacquire(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    acquire_cycle_lock(ctx, "A")  # no raise
    assert ctx.current_sub_bid == "A"


def test_p2_release_clears_lock(tmp_path):
    ctx = _context(tmp_path)
    acquire_cycle_lock(ctx, "A")
    release_cycle_lock(ctx)
    assert ctx.current_sub_bid is None
    acquire_cycle_lock(ctx, "B")  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p2"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Append P2 to policy.py**

Append to `src/mage/orchestration/discipline/policy.py`:

```python
from mage.orchestration.nodes import PipelineContext


# P2 — Sequential per-scenario cycles
def acquire_cycle_lock(context: PipelineContext, sub_bid: str) -> None:
    """Acquire the cycle lock for `sub_bid`. Reacquire by same sub_bid is allowed."""
    if context.current_sub_bid is not None and context.current_sub_bid != sub_bid:
        raise CycleAlreadyInProgress(
            f"cycle lock held by sub_bid {context.current_sub_bid!r}; "
            f"cannot start {sub_bid!r}"
        )
    # PipelineContext is mutable; direct assignment is the existing pattern.
    context.current_sub_bid = sub_bid


def release_cycle_lock(context: PipelineContext) -> None:
    """Release the cycle lock. Safe to call when unset."""
    context.current_sub_bid = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p2"`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add P2 sequential cycle lock"
```

---

### Task 6: Policy P3 — guard automation entry

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py`
- Modify: `tests/unit/test_discipline_policy.py`

**Interfaces:**
- Produces: `guard_automation_entry(scenario) -> None`

- [ ] **Step 1: Append failing tests**

```python
from mage.orchestration.discipline.policy import guard_automation_entry


def test_p3_passes_when_approved():
    s = _scenario("A", LifecycleStatus.APPROVED)
    guard_automation_entry(s)


def test_p3_raises_when_inscribing():
    s = _scenario("A", LifecycleStatus.INSCRIBING)
    with pytest.raises(NotApprovedForAutomation):
        guard_automation_entry(s)


def test_p3_raises_when_live():
    s = _scenario("A", LifecycleStatus.LIVE)
    with pytest.raises(NotApprovedForAutomation):
        guard_automation_entry(s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p3"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Append P3**

Append to `src/mage/orchestration/discipline/policy.py`:

```python
# P3 — Approved before any Etch/Realize sub-phase
def guard_automation_entry(scenario: ScenarioEntry) -> None:
    """Automation sub-phases require scenario.lifecycle_status == APPROVED."""
    if scenario.lifecycle_status != LifecycleStatus.APPROVED:
        raise NotApprovedForAutomation(
            f"scenario {scenario.sub_bid!r} has status "
            f"{scenario.lifecycle_status.value!r}; must be APPROVED before Automation"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p3"`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add P3 automation entry guard"
```

---

### Task 7: Policy P4 — decomposition closed

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py`
- Modify: `tests/unit/test_discipline_policy.py`

**Interfaces:**
- Produces: `assert_decomposition_closed(plan_path, events_log) -> None`

- [ ] **Step 1: Append failing tests**

```python
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.discipline.policy import assert_decomposition_closed


def _log(tmp_path: Path) -> EventsLog:
    return EventsLog(tmp_path / "events.jsonl")


def _emit(log: EventsLog, event_type: EventType, payload: dict) -> None:
    from datetime import datetime, timezone
    log.append(Event(timestamp=datetime.now(timezone.utc), event_type=event_type, payload=payload))


def test_p4_passes_when_plan_finalized_event_present(tmp_path):
    log = _log(tmp_path)
    _emit(log, EventType.PLAN_FINALIZED, {"plan_path": str(tmp_path / "plan.md"), "plan_sha256": "abc"})
    assert_decomposition_closed(tmp_path / "plan.md", log)  # no raise


def test_p4_passes_when_plan_revised_event_present(tmp_path):
    log = _log(tmp_path)
    _emit(log, EventType.PLAN_REVISED, {"plan_path": str(tmp_path / "plan.md"), "plan_sha256": "abc"})
    assert_decomposition_closed(tmp_path / "plan.md", log)


def test_p4_raises_when_no_finalized_event(tmp_path):
    log = _log(tmp_path)
    with pytest.raises(DecompositionOpen):
        assert_decomposition_closed(tmp_path / "plan.md", log)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p4"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Append P4**

Append to `src/mage/orchestration/discipline/policy.py`:

```python
# P4 — Decomposition closed before any per-scenario cycle starts
def assert_decomposition_closed(plan_path: Path, events_log: EventsLog) -> None:
    """Per-scenario cycles require a finalized Plan (PLAN_FINALIZED or PLAN_REVISED)."""
    try:
        PlanArtifact.load(plan_path, events_log)
    except PlanNotFinalizedError as e:
        raise DecompositionOpen(
            f"Plan at {plan_path} not finalized; per-scenario cycles blocked"
        ) from e
```

Add `from pathlib import Path` at top of `policy.py` if not present.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p4"`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add P4 decomposition-closed guard"
```

---

### Task 8: Policy P5 — begin revision

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py`
- Modify: `tests/unit/test_discipline_policy.py`

**Interfaces:**
- Produces: `begin_revision(mapping, sub_bid, reason, originating_stage, timestamp) -> MappingArtifact`

- [ ] **Step 1: Append failing tests**

```python
from datetime import datetime, timezone
from mage.orchestration.discipline.policy import begin_revision


def _now() -> datetime:
    return datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_p5_flips_status_to_inscribing():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED)])
    out = begin_revision(m, "A", "spec ambiguity in step 2", "inspect_loop", _now())
    assert out.lookup_sub_bid(_make_base85("00000"), "A").lifecycle_status == LifecycleStatus.INSCRIBING


def test_p5_appends_reversion_log_entry_to_correct_base_bid_entry():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED)])
    out = begin_revision(m, "A", "reason", "inspect_loop", _now())
    entry = out.base_bids[0]
    assert len(entry.reversion_log) == 1
    assert entry.reversion_log[0].sub_bid == "A"
    assert entry.reversion_log[0].reason == "reason"
    assert entry.reversion_log[0].originating_stage == "inspect_loop"


def test_p5_preserves_earlier_reversions():
    from mage.artifacts.mapping import ReversionLogEntry
    earlier = ReversionLogEntry(sub_bid="A", timestamp=_now(), reason="r1", originating_stage="s1")
    entry = BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d",
                         scenarios=[_scenario("A", LifecycleStatus.APPROVED)],
                         reversion_log=[earlier])
    m = MappingArtifact(project_id="p", base_bids=[entry])
    out = begin_revision(m, "A", "r2", "s2", _now())
    assert len(out.base_bids[0].reversion_log) == 2


def test_p5_raises_when_sub_bid_not_found():
    m = _mapping([])
    with pytest.raises(ForwardOrderViolation):
        begin_revision(m, "MISSING", "r", "s", _now())


# helper for first P5 test
from mage.artifacts.bid import Base85BID
def _make_base85(v: str) -> Base85BID:
    return Base85BID(value=v)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p5"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Append P5**

Append to `src/mage/orchestration/discipline/policy.py`:

```python
# P5 — Revision re-applies the gate
def begin_revision(
    mapping: MappingArtifact,
    sub_bid: str,
    reason: str,
    originating_stage: str,
    timestamp: datetime,
) -> MappingArtifact:
    """Revert scenario to inscribing; append ReversionLogEntry."""
    new_entries: list[BaseBIDEntry] = []
    matched = False
    for entry in mapping.base_bids:
        new_scenarios: list[ScenarioEntry] = []
        scenario_found = False
        for scenario in entry.scenarios:
            if scenario.sub_bid == sub_bid:
                scenario_found = True
                new_scenarios.append(
                    scenario.model_copy(update={"lifecycle_status": LifecycleStatus.INSCRIBING})
                )
            else:
                new_scenarios.append(scenario)
        if scenario_found:
            matched = True
            new_log = [
                *entry.reversion_log,
                ReversionLogEntry(
                    sub_bid=sub_bid,
                    timestamp=timestamp,
                    reason=reason,
                    originating_stage=originating_stage,
                ),
            ]
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios, "reversion_log": new_log}))
        else:
            new_entries.append(entry)
    if not matched:
        raise ForwardOrderViolation(f"sub_bid {sub_bid!r} not found in mapping; cannot revise")
    return mapping.model_copy(update={"base_bids": new_entries})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "p5"`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add P5 begin_revision"
```

---

### Task 9: Policy — supersession (begin + complete)

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py`
- Modify: `tests/unit/test_discipline_policy.py`

**Interfaces:**
- Produces: `begin_supersession(mapping, old_sub_bid, new_sub_bid, reason, timestamp) -> MappingArtifact`
- Produces: `complete_supersession(mapping, new_sub_bid, timestamp) -> MappingArtifact`

- [ ] **Step 1: Append failing tests**

```python
from mage.orchestration.discipline.policy import (
    begin_supersession,
    complete_supersession,
)


def test_supersession_begin_sets_supersedes_link_on_new():
    # old in one base_bid, new in another
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[_scenario("N", LifecycleStatus.INSCRIBING)])
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("O", LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    out = begin_supersession(m, "O", "N", "new spec", _now())
    new = next(s for entry in out.base_bids for s in entry.scenarios if s.sub_bid == "N")
    assert new.supersedes == "O"


def test_supersession_complete_flips_old_to_deprecated():
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[_scenario("N", LifecycleStatus.APPROVED, supersedes="O")])
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("O", LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    out = complete_supersession(m, "N", _now())
    old = next(s for entry in out.base_bids for s in entry.scenarios if s.sub_bid == "O")
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED
    assert old.superseded_by == "N"


def test_supersession_complete_writes_reversion_log_entry():
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[_scenario("N", LifecycleStatus.APPROVED, supersedes="O")])
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("O", LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    out = complete_supersession(m, "N", _now())
    old_entry = next(e for e in out.base_bids if any(s.sub_bid == "O" for s in e.scenarios))
    assert any(log.reason.startswith("superseded by") for log in old_entry.reversion_log)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "supersession"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Append supersession functions**

Append to `src/mage/orchestration/discipline/policy.py`:

```python
# Supersession (full only in v1)
def begin_supersession(
    mapping: MappingArtifact,
    old_sub_bid: str,
    new_sub_bid: str,
    reason: str,
    timestamp: datetime,
) -> MappingArtifact:
    """Mark new scenario as superseding old. Old stays live until new reaches live."""
    new_entries: list[BaseBIDEntry] = []
    for entry in mapping.base_bids:
        new_scenarios = [
            (s.model_copy(update={"supersedes": old_sub_bid}) if s.sub_bid == new_sub_bid else s)
            for s in entry.scenarios
        ]
        if any(s.sub_bid == old_sub_bid for s in entry.scenarios):
            new_log = [
                *entry.reversion_log,
                ReversionLogEntry(
                    sub_bid=old_sub_bid,
                    timestamp=timestamp,
                    reason=reason,
                    originating_stage="supersession",
                ),
            ]
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios, "reversion_log": new_log}))
        else:
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios}))
    return mapping.model_copy(update={"base_bids": new_entries})


def complete_supersession(
    mapping: MappingArtifact,
    new_sub_bid: str,
    timestamp: datetime,
) -> MappingArtifact:
    """Flip old scenario to DEPRECATED when new scenario reaches LIVE."""
    # Find the new scenario's supersedes target
    target_old: str | None = None
    for entry in mapping.base_bids:
        for s in entry.scenarios:
            if s.sub_bid == new_sub_bid:
                target_old = s.supersedes
                break
        if target_old:
            break
    if target_old is None:
        raise ForwardOrderViolation(f"new sub_bid {new_sub_bid!r} has no supersedes link")

    new_entries: list[BaseBIDEntry] = []
    for entry in mapping.base_bids:
        new_scenarios: list[ScenarioEntry] = []
        for s in entry.scenarios:
            if s.sub_bid == target_old:
                new_scenarios.append(
                    s.model_copy(update={
                        "lifecycle_status": LifecycleStatus.DEPRECATED,
                        "superseded_by": new_sub_bid,
                    })
                )
            else:
                new_scenarios.append(s)
        if any(s.sub_bid == target_old for s in entry.scenarios):
            new_log = [
                *entry.reversion_log,
                ReversionLogEntry(
                    sub_bid=target_old,
                    timestamp=timestamp,
                    reason=f"superseded by {new_sub_bid}",
                    originating_stage="supersession_complete",
                ),
            ]
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios, "reversion_log": new_log}))
        else:
            new_entries.append(entry.model_copy(update={"scenarios": new_scenarios}))
    return mapping.model_copy(update={"base_bids": new_entries})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "supersession"`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add supersession begin and complete"
```

---

### Task 10: Policy — cosmetic guard

**Files:**
- Modify: `src/mage/orchestration/discipline/policy.py`
- Modify: `tests/unit/test_discipline_policy.py`

**Interfaces:**
- Produces: `guard_cosmetic_application(source, item, human_approver) -> PostLiveRevisionEntry`

- [ ] **Step 1: Append failing tests**

```python
from mage.artifacts.inspect import CosmeticItem
from mage.orchestration.discipline.policy import guard_cosmetic_application


def _cosmetic() -> CosmeticItem:
    return CosmeticItem(sub_bid="A", location="text", issue="typo", rationale="r", route="cosmetic")


def test_cosmetic_guard_rejects_model_source():
    with pytest.raises(ModelCannotApplyCosmetic):
        guard_cosmetic_application(source="model", item=_cosmetic(), human_approver=None)


def test_cosmetic_guard_accepts_human_source():
    out = guard_cosmetic_application(source="human", item=_cosmetic(), human_approver="alice")
    assert out.sub_bid == "A"
    assert out.human_approver == "alice"


def test_cosmetic_guard_accepts_human_authorized_source():
    out = guard_cosmetic_application(source="human-authorized", item=_cosmetic(), human_approver="ci-bot")
    assert out.human_approver == "ci-bot"


def test_cosmetic_guard_requires_human_approver_for_human_source():
    with pytest.raises(ModelCannotApplyCosmetic):
        guard_cosmetic_application(source="human", item=_cosmetic(), human_approver=None)
```

Note: `ModelCannotApplyCosmetic` raised for both model source and missing approver, since the policy intent is "no human, no apply." Test asserts same exception class for both.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "cosmetic_guard"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Append cosmetic guard**

Append to `src/mage/orchestration/discipline/policy.py`:

```python
from mage.artifacts.inspect import CosmeticItem


# Cosmetic gate (parent v2 design line 327)
def guard_cosmetic_application(
    source: str,
    item: CosmeticItem,
    human_approver: str | None,
) -> PostLiveRevisionEntry:
    """Build a PostLiveRevisionEntry. Reject model source; require human approver."""
    if source not in ("human", "human-authorized") or not human_approver:
        raise ModelCannotApplyCosmetic(
            f"cosmetic application source={source!r} with approver={human_approver!r} "
            f"rejected; live-scenario text changes require human authorization"
        )
    from datetime import datetime, timezone
    return PostLiveRevisionEntry(
        sub_bid=item.sub_bid,
        timestamp=datetime.now(timezone.utc),
        human_approver=human_approver,
        before_hash="",
        after_hash="",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_policy.py -v -k "cosmetic_guard"`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/policy.py tests/unit/test_discipline_policy.py
git commit -m "feat(discipline): add cosmetic application gate"
```

---

### Task 11: Wire P3 into AutomationStage

**Files:**
- Modify: `src/mage/orchestration/automation.py:30-35`

**Interfaces:**
- Consumes: existing `AutomationStage.run_scenario` accepting `(context, target)` returning `ScenarioOutcome`
- Produces: same return type; first action is `guard_automation_entry(scenario)` call

- [ ] **Step 1: Read existing automation.py**

```bash
sed -n '20,80p' src/mage/orchestration/automation.py
```

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_automation_stage.py` (existing file):

```python
from mage.orchestration.discipline.policy import guard_automation_entry


def test_automation_stage_rejects_non_approved_scenario():
    """P3 enforcement at the AutomationStage entry point."""
    # Use the existing test fixture pattern from the file. Test that calling
    # the stage with a non-APPROVED scenario raises NotApprovedForAutomation.
    pass  # Implementation note: build a context with a non-approved scenario and assert raises
```

Replace `pass` with a concrete test that constructs the context and calls into the stage. Match the existing fixture patterns in `test_automation_stage.py` if present.

- [ ] **Step 3: Add guard_automation_entry call**

In `src/mage/orchestration/automation.py`, at the top of `run_scenario` (or its equivalent entry method — confirm by reading), add:

```python
from mage.orchestration.discipline.policy import guard_automation_entry

# ... inside run_scenario, before dispatching Etch:
scenario = context.mapping.lookup_sub_bid(target.base_bid, target.sub_bid)
if scenario is None:
    raise NotApprovedForAutomation(...)
guard_automation_entry(scenario)
```

(The exact import / lookup pattern must match what `run_scenario` already does. If it already looks up the scenario, just insert `guard_automation_entry(scenario)` after the lookup.)

- [ ] **Step 4: Run automation tests**

Run: `uv run pytest tests/unit/test_automation_stage.py -v`
Expected: PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/automation.py tests/unit/test_automation_stage.py
git commit -m "feat(automation): enforce P3 guard before Etch dispatch"
```

---

### Task 12: Wire P2 into InscribeStage

**Files:**
- Modify: `src/mage/orchestration/inscribe.py`

**Interfaces:**
- Produces: `acquire_cycle_lock(context, sub_bid)` call at scenario entry; `release_cycle_lock(context)` on `SCENARIO_APPROVED` event

- [ ] **Step 1: Read existing inscribe.py**

```bash
grep -n "current_sub_bid\|acquire_cycle\|release_cycle" src/mage/orchestration/inscribe.py
```

- [ ] **Step 2: Insert acquire/release calls**

In `inscribe.py`, at the entry point of per-scenario Inscribe (where the scenario is identified), insert:

```python
from mage.orchestration.discipline.policy import acquire_cycle_lock, release_cycle_lock

# Acquire lock at entry
acquire_cycle_lock(context, scenario.sub_bid)
```

Wherever `SCENARIO_APPROVED` is currently emitted (grep for it), insert immediately before the emit:

```python
release_cycle_lock(context)
```

- [ ] **Step 3: Run inscribe tests**

Run: `uv run pytest tests/unit/test_inscribe_stage.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/mage/orchestration/inscribe.py
git commit -m "feat(inscribe): acquire cycle lock at scenario entry"
```

---

### Task 13: DisciplineStage — event subscription wiring

**Files:**
- Create: `src/mage/orchestration/discipline/stage.py`
- Test: `tests/unit/test_discipline_stage.py`

**Interfaces:**
- Produces: `DisciplineStage` class extending `StageNode`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_discipline_stage.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.discipline.policy import begin_revision
from mage.orchestration.discipline.stage import DisciplineStage
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext


def _ctx(tmp_path: Path, scenario_status: LifecycleStatus = LifecycleStatus.LIVE) -> PipelineContext:
    m = MappingArtifact(
        project_id="p",
        base_bids=[BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d",
                                 scenarios=[ScenarioEntry(sub_bid="A", scenario_text_hash="h",
                                                          lifecycle_status=scenario_status)])],
    )
    return PipelineContext(project_dir=tmp_path, mapping=m,
                           events_log=EventsLog(tmp_path / "events.jsonl"))


def test_stage_releases_lock_on_scenario_approved(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.APPROVED)
    ctx.current_sub_bid = "A"
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(ctx, Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.SCENARIO_APPROVED,
        payload={"sub_bid": "A"},
    ))
    assert ctx.current_sub_bid is None


def test_stage_calls_begin_revision_on_revision_requested(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.LIVE)
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(ctx, Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.SCENARIO_REVISION_REQUESTED,
        payload={"sub_bid": "A", "reason": "r", "originating_stage": "inspect_loop"},
    ))
    new_status = ctx.mapping.lookup_sub_bid(ctx.mapping.highest_base_bid(), "A").lifecycle_status
    assert new_status == LifecycleStatus.INSCRIBING


def test_stage_calls_begin_supersession_on_supersession_requested(tmp_path):
    new_entry = BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                             scenarios=[ScenarioEntry(sub_bid="N", scenario_text_hash="h",
                                                      lifecycle_status=LifecycleStatus.INSCRIBING)])
    ctx = _ctx(tmp_path)
    ctx.mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[ScenarioEntry(sub_bid="O", scenario_text_hash="h",
                                                  lifecycle_status=LifecycleStatus.LIVE)]),
            new_entry,
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(ctx, Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.SCENARIO_SUPERSESSION_REQUESTED,
        payload={"old_sub_bid": "O", "new_sub_bid": "N", "reason": "new spec"},
    ))
    new = next(s for e in ctx.mapping.base_bids for s in e.scenarios if s.sub_bid == "N")
    assert new.supersedes == "O"


def test_stage_completes_pending_supersession_on_scenario_live(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[ScenarioEntry(sub_bid="O", scenario_text_hash="h",
                                                  lifecycle_status=LifecycleStatus.LIVE)]),
            BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                         scenarios=[ScenarioEntry(sub_bid="N", scenario_text_hash="h",
                                                  lifecycle_status=LifecycleStatus.APPROVED,
                                                  supersedes="O")]),
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(ctx, Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.SCENARIO_LIVE,
        payload={"sub_bid": "N"},
    ))
    old = next(s for e in ctx.mapping.base_bids for s in e.scenarios if s.sub_bid == "O")
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED
    assert old.superseded_by == "N"


def test_stage_idempotent_on_duplicate_scenario_approved(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.APPROVED)
    ctx.current_sub_bid = "A"
    stage = DisciplineStage(ctx.events_log)
    for _ in range(3):
        stage._handle_event(ctx, Event(
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.SCENARIO_APPROVED,
            payload={"sub_bid": "A"},
        ))
    assert ctx.current_sub_bid is None


def test_stage_emits_reverted_event_on_revision(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.LIVE)
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(ctx, Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.SCENARIO_REVISION_REQUESTED,
        payload={"sub_bid": "A", "reason": "r", "originating_stage": "inspect_loop"},
    ))
    events = ctx.events_log.read_all()
    assert any(e.event_type == EventType.SCENARIO_REVERTED_TO_INSCRIBING for e in events)
    assert any(e.event_type == EventType.REVERSION_LOGGED for e in events)


def test_stage_emits_deprecated_event_on_supersession_complete(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[ScenarioEntry(sub_bid="O", scenario_text_hash="h",
                                                  lifecycle_status=LifecycleStatus.LIVE)]),
            BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                         scenarios=[ScenarioEntry(sub_bid="N", scenario_text_hash="h",
                                                  lifecycle_status=LifecycleStatus.APPROVED,
                                                  supersedes="O")]),
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(ctx, Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.SCENARIO_LIVE,
        payload={"sub_bid": "N"},
    ))
    events = ctx.events_log.read_all()
    assert any(e.event_type == EventType.SCENARIO_DEPRECATED for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_discipline_stage.py -v`
Expected: FAIL with `ModuleNotFoundError: mage.orchestration.discipline.stage`

- [ ] **Step 3: Create the stage**

```python
# src/mage/orchestration/discipline/stage.py
"""DisciplineStage: Pydantic-Graph node that enforces Three Practices.

The stage is event-driven. Existing pipeline stages emit the events listed
below; DisciplineStage reacts. The stage is pure: it mutates context.mapping
through Policy methods and emits audit events. It does not run agents.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.discipline.policy import (
    begin_revision,
    begin_supersession,
    complete_supersession,
    release_cycle_lock,
)


class DisciplineStage(StageNode):
    name = "discipline"

    def __init__(self, events_log: EventsLog) -> None:
        super().__init__(events_log)

    def _run(self, context: PipelineContext) -> PipelineContext:
        """No proactive work — DisciplineStage reacts to events.

        The actual enforcement happens when other stages emit events that this
        stage subscribes to. Pydantic-Graph calls `_run` once per scenario cycle;
        this no-op keeps the stage compatible with the graph shape.
        """
        return context

    def _handle_event(self, context: PipelineContext, event: Event) -> None:
        """Public hook for the orchestrator to invoke on each emitted event.

        Routes events to the matching policy method. Idempotent on repeat
        emissions of the same event for the same scenario.
        """
        et = event.event_type
        payload = event.payload

        if et == EventType.SCENARIO_APPROVED:
            release_cycle_lock(context)
            return

        if et == EventType.SCENARIO_REVISION_REQUESTED:
            sub_bid = payload["sub_bid"]
            context.mapping = begin_revision(
                mapping=context.mapping,
                sub_bid=sub_bid,
                reason=payload.get("reason", ""),
                originating_stage=payload.get("originating_stage", "unknown"),
                timestamp=event.timestamp,
            )
            self._emit(EventType.SCENARIO_REVERTED_TO_INSCRIBING, {"sub_bid": sub_bid})
            self._emit(EventType.REVERSION_LOGGED, {"sub_bid": sub_bid})
            return

        if et == EventType.SCENARIO_SUPERSESSION_REQUESTED:
            context.mapping = begin_supersession(
                mapping=context.mapping,
                old_sub_bid=payload["old_sub_bid"],
                new_sub_bid=payload["new_sub_bid"],
                reason=payload.get("reason", ""),
                timestamp=event.timestamp,
            )
            return

        if et == EventType.SCENARIO_LIVE:
            new_sub_bid = payload.get("sub_bid")
            if new_sub_bid is None:
                return
            # Check if this scenario supersedes another
            for entry in context.mapping.base_bids:
                for s in entry.scenarios:
                    if s.sub_bid == new_sub_bid and s.supersedes is not None:
                        context.mapping = complete_supersession(
                            mapping=context.mapping,
                            new_sub_bid=new_sub_bid,
                            timestamp=event.timestamp,
                        )
                        self._emit(EventType.SCENARIO_DEPRECATED,
                                   {"old_sub_bid": s.supersedes, "new_sub_bid": new_sub_bid})
                        return
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_discipline_stage.py -v`
Expected: PASS (7/7)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/discipline/stage.py tests/unit/test_discipline_stage.py
git commit -m "feat(discipline): add DisciplineStage event handler"
```

---

### Task 14: Wire DisciplineStage into orchestrator

**Files:**
- Modify: `src/mage/orchestration/runner.py` (or the file holding `cmd_run`'s orchestrator) — pass `events_log` to construct a `DisciplineStage` and wire its `_handle_event` to the events log subscription.

**Interfaces:**
- Consumes: existing orchestrator
- Produces: orchestrator that invokes `DisciplineStage._handle_event` for each new event in `EventsLog`

- [ ] **Step 1: Read the orchestrator**

```bash
grep -n "def.*run\|EventsLog\|events_log" src/mage/orchestration/runner.py src/mage/cli.py 2>&1 | head -20
```

- [ ] **Step 2: Add event subscription**

In the orchestrator (wherever `cmd_run` drives the pipeline), after each event is appended to `events_log`, also call `discipline_stage._handle_event(context, event)`. The simplest pattern is a tail-reader on `events_log` that diffs previous vs new entries and dispatches each to `DisciplineStage._handle_event`.

Reference implementation pattern:

```python
from mage.orchestration.discipline.stage import DisciplineStage

discipline = DisciplineStage(events_log)
last_seen_count = 0
while pipeline_active:
    events = events_log.read_all()
    for event in events[last_seen_count:]:
        discipline._handle_event(context, event)
    last_seen_count = len(events)
    # ... rest of pipeline loop
```

Exact integration depends on how the existing orchestrator is structured. Match the surrounding loop pattern.

- [ ] **Step 3: Run all unit tests**

Run: `uv run pytest tests/unit -v`
Expected: PASS (existing tests + 17 new discipline tests)

- [ ] **Step 4: Commit**

```bash
git add src/mage/orchestration/runner.py src/mage/cli.py
git commit -m "feat(orchestrator): wire DisciplineStage event handler"
```

---

### Task 15: E2E — revision full loop

**Files:**
- Create: `tests/features/test_e2e_three_practices.py`

- [ ] **Step 1: Write the test**

```python
# tests/features/test_e2e_three_practices.py — first test
from mage.orchestration.discipline.policy import begin_revision
# ... use existing fixture patterns from test_e2e_inscribe.py and test_e2e_run.py
```

Follow the existing e2e test fixture patterns. The test:

1. Builds a project with one scenario mapped
2. Runs pipeline to `SCENARIO_APPROVED`
3. Calls `begin_revision` directly (simulating Inspect-loop spec finding)
4. Verifies scenario `lifecycle_status == INSCRIBING`
5. Verifies `reversion_log` has one entry
6. Re-runs Inscribe (full mechanical + reviewers)
7. Verifies scenario reaches `APPROVED` again

Reference existing `tests/features/test_e2e_inscribe.py` for the project fixture pattern.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/features/test_e2e_three_practices.py::test_e2e_revision_full_loop -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/features/test_e2e_three_practices.py
git commit -m "test(e2e): full revision loop end-to-end"
```

---

### Task 16: E2E — supersession full loop

**Files:**
- Modify: `tests/features/test_e2e_three_practices.py`

- [ ] **Step 1: Write the test**

```python
def test_e2e_supersession_full_loop():
    # 1. Build project with old scenario live
    # 2. Emit SCENARIO_SUPERSESSION_REQUESTED with new_sub_bid
    # 3. Run new scenario through full cycle to SCENARIO_LIVE
    # 4. Verify old flipped to DEPRECATED, old.superseded_by == new
    ...
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/features/test_e2e_three_practices.py::test_e2e_supersession_full_loop -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/features/test_e2e_three_practices.py
git commit -m "test(e2e): full supersession loop end-to-end"
```

---

### Task 17: E2E — cosmetic model-blocked, plan order violation, decomposition open

**Files:**
- Modify: `tests/features/test_e2e_three_practices.py`

- [ ] **Step 1: Write the three tests**

```python
def test_e2e_cosmetic_model_blocked():
    # Live scenario; cosmetic item; guard with source="model" → ModelCannotApplyCosmetic
    ...

def test_e2e_plan_order_violation():
    # Two scenarios; scenario 1 INSCRIBING; scenario 2 attempts start → ForwardOrderViolation
    ...

def test_e2e_decomposition_open_blocks_pipeline_start():
    # Empty events log (no PLAN_FINALIZED) → DecompositionOpen
    ...
```

- [ ] **Step 2: Run all e2e tests**

Run: `uv run pytest tests/features/test_e2e_three_practices.py -v`
Expected: PASS (5/5)

- [ ] **Step 3: Commit**

```bash
git add tests/features/test_e2e_three_practices.py
git commit -m "test(e2e): cosmetic, plan order, decomposition open end-to-end"
```

---

### Task 18: Final regression + whole-suite verification

- [ ] **Step 1: Run lint, typecheck, format**

```bash
make check
```

Expected: PASS (no regressions; new files may trigger minor pyright warnings that resolve on next run).

- [ ] **Step 2: Run full test suite**

```bash
make test
```

Expected: PASS (334 existing + ~30 new discipline tests, total ~364).

- [ ] **Step 3: Final commit if any format/lint fixes**

```bash
git status
# If changes from `make check`, commit:
git add -u
git commit -m "style: ruff auto-fix import order on Plan 7 discipline files"
```

---

## Spec Self-Review (post-write)

1. **Spec coverage:** All six Approved Gate Scope rules mapped (P1-Task4, P2-Task5, P3-Task6, P4-Task7, P5-Task8, P6-implicit-in-Task8 since reversion_log is the audit). Revision flow = Tasks 8, 11, 12, 13, 14, 15. Supersession flow = Tasks 9, 13, 14, 16. Cosmetic gate = Task 10. E2E coverage = Tasks 15-17.
2. **Placeholder scan:** No "TBD". All event type names match spec. All exception names match spec. `ScenarioEntry.supersedes` / `superseded_by` reuse confirmed (Plan 1 fields). `current_sub_bid` field confirmed present on `PipelineContext` (Task 5 reuses without schema change). Cosmetic "stub writes empty hashes" pinned.
3. **Internal consistency:** Tasks 11 (wire P3 into AutomationStage) and 12 (wire P2 into InscribeStage) precede Task 14 (orchestrator integration). E2E tests follow unit tests. Test counts pinned per task.
4. **Ambiguity check:** Task 10 specifies both `model` source rejection AND missing-approver rejection raise the same exception class (`ModelCannotApplyCosmetic`) since both fail the "no human, no apply" intent. Task 11 specifies that `run_scenario`'s scenario lookup is reused (no duplicate code). Task 14 leaves orchestrator integration pattern flexible to match existing structure.
