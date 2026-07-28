# HAILERIS v2 — Plan 3 (Inscribe + 7 Reviewers + Verdict Format) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Inscribe stage of the HAILERIS v2 pipeline — per behavior, draft scenarios, run the mechanical pre-check + 7 judgmental reviewers, aggregate verdicts, and gate each scenario to APPROVED. Provide the structured verdict format (per-reviewer + aggregate), a digest-pinned `VerdictArtifact`, the seven reviewer dimensions, and the CLI surface for inspecting verdicts and resuming after budget-exhaustion halts.

**Architecture:** An `InscribeStage` (Plan 1's `StageNode` subclass) that loops over each behavior from `behaviors.yaml`. For each behavior, it drives the per-scenario Formulation cycle: Pydantic-AI `InscribeAgent` drafts `ScenarioSpec`s, the Plan 1 `MechanicalVerifier` runs 7 deterministic checks, then 7 judgmental `ReviewerAgent` subclasses emit per-dimension verdicts. A `VerdictArtifact` mirrors `PlanArtifact`'s digest-pinned API. Aggregate → decision gate (all-7-pass → APPROVED, any-fail + budget → needs_refactor, budget exhausted → halt). Sub-BIDs are assigned at the APPROVED transition via `Base85BID.derive(parent_base_bid, scenario_index)`.

**Tech Stack:** Python 3.12+, Pydantic v2, Pydantic-AI, Pydantic-Graph, pytest, pyyaml, uv (package manager), hatchling (build backend).

## Global Constraints

These are project-wide requirements that every task's implementation implicitly satisfies. Plan 1+2 constraints are inherited; Plan 3 additions are below.

**Plan 1+2 (inherited verbatim):**

- **BID format:** Base85 alphabet, monotonically increasing within tier. Base BIDs are 5-digit Base85; sub-BIDs are appended Base85 characters using the same alphabet. Combination `<base>-<sub>` is globally unique.
- **BIDs never reused:** A retired BID stays retired permanently.
- **Mapping artifact is project-level, single source of truth:** `mapping.yaml` at the project root.
- **Mechanical verification is deterministic:** No LLM calls.
- **Persistence is append-only for events:** `events.jsonl` is append-only; never edited in place. State files are written atomically (write-temp-then-rename).
- **All Pydantic models use `model_config = ConfigDict(frozen=True)` where state is meant to be immutable.**
- **Package name:** `mage`. All imports use `from mage.X import Y`. CLI entry point: `mage.cli:main`.
- **Plan format:** Markdown + YAML frontmatter; SHA256 digest pinned in events log.
- **BID assignment:** Agent emits specs without BIDs. System assigns.
- **Approval gate:** `HostConfig.require_plan_approval: bool = True` (default: required).
- **Halt mechanism:** `PlanRevisionRequired` exception caught by `PipelineGraph.run()`, halts via `HALT_PERSISTED` event + `FileStatePersistence.save_state()`, exits with code 0.

**Plan 3 additions:**

- **Inscribe loop unit:** `InscribeStage` runs once per feature, looping internally over each behavior from `behaviors.yaml`. For each behavior, it iterates scenarios through draft → mechanical pre-check → 7 reviewers → aggregate → decision gate. The `iteration` counter in `PipelineContext` persists across scenarios of the same feature; mechanical pre-check and 7 reviewers share the same counter.
- **Sub-BID assignment timing:** Sub-BIDs are assigned **at the moment a scenario transitions to APPROVED** (not at draft). Done via `Base85BID.derive(parent_base_bid, scenario_index)` — a new classmethod on Plan 1's `Base85BID`. The `sub_bid_assigned` mechanical check is satisfied only after this point.
- **The 7 reviewer dimensions:** `spec_compliance`, `scenario_clarity`, `step_grammar`, `testability`, `determinism`, `naming_idiom`, `lifecycle_tags`. Each is a separate Pydantic-AI subagent under `verification/reviewers/<dimension>.py`; all share the same input (draft scenario + spec context + mapping excerpt) and produce the same `ReviewerVerdict` schema.
- **Verdict format (per-reviewer):** YAML with `dimension`, `outcome` (`pass`|`fail`), `draft_hash`, `reviewed_at`, `reviewer_id`, `findings[]` (`id`, `severity`, `location`, `issue`, `rationale` mandatory, `suggestion`, `citations`), `notes`. Digest-pinned via `VerdictArtifact` (mirrors `PlanArtifact`).
- **Verdict format (aggregate):** YAML with `draft_hash`, `aggregated_at`, `iteration`, `per_dimension` (per-dimension summary: `outcome`, `reviewer_verdict_ref`, `findings_count`), `decision` (`approved`|`needs_refactor`|`needs_human_review`), `reasoning`.
- **Decision gate:** all 7 dimensions pass → `approved`; any fail + `iteration < max_iterations` → `needs_refactor` (loop); any fail + `iteration >= max_iterations` → `needs_human_review` (halt via Plan 2 mechanism). `max_iterations` defaults to 3, host-configurable. Severity does not affect gate outcome; any fail triggers refactor regardless of severity. Rationale is mandatory per finding.
- **Approved-gate scope (six rules):** (1) per-scenario independence; (2) sequential per-scenario cycles within a behavior (concurrency deferred to Plan 6); (3) approved before any Etch/Realize sub-phase (Plan 4 refuses to start without `SCENARIO_APPROVED` for that sub-BID); (4) Decomposition closed before per-scenario cycle starts (Plan 3 emits the event but doesn't enforce — Plan 5/6 territory); (5) revision re-applies gate (Plan 5); (6) reversion logged in mapping artifact via `ReversionLogEntry`.
- **Verdict storage layout:** `<project_dir>/.haileris/verdicts/<draft_hash>/<dimension>.yaml` (×7) and `<draft_hash>.aggregate.yaml` (×1 per iteration). Digest computed on `content` (the YAML body, serialized).
- **Approved-scenario file output:** `<project_dir>/scenarios/<base_bid>/<scenario_name>.feature` written for each approved scenario.
- **HostConfig additions:** `max_iterations: int = 3` and `enabled_reviewers: list[str] | None = None` (None = all 7 enabled).
- **New EventType members:** `INSCRIBE_STARTED`, `INSCRIBE_COMPLETED`, `BEHAVIOR_INSCRIBE_STARTED`, `BEHAVIOR_INSCRIBE_COMPLETED`, `SCENARIO_DRAFTED`, `MECHANICAL_PRECHECK_PASSED`, `MECHANICAL_PRECHECK_FAILED`, `REVIEWER_VERDICT_RECORDED`, `REVIEW_AGGREGATE_RECORDED`, `SCENARIO_APPROVED`, `SCENARIO_NEEDS_REFACTOR`, `REVIEW_HALT_PERSISTED`.
- **Mapping extension:** `MappingArtifact.append_scenario(base_bid, scenario) -> MappingArtifact` helper for atomic scenario append (Plan 3 addition).
- **ScenarioSpec shape:** `name`, `gherkin_body`, `tags`, `notes`, `cross_behavior_tags`. Sub-BID and `scenario_text_hash` assigned by system at APPROVED only.

**Test count target:** ~43 new tests in Plan 3. Combined with Plan 2's 128 tests, total ~171 by end of Plan 3. Maintain ≥90% line coverage on new code.

---

### Task 1: Add 11 Plan 3 EventType members

**Files:**
- Modify: `src/mage/orchestration/events.py`
- Test: `tests/test_events.py` (Plan 1, extend)

**Interfaces:**
- Consumes: existing `EventType` enum (Plan 1+2).
- Produces: 11 new `EventType` members per the Plan 3 Global Constraints.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_events.py`:

```python
def test_plan3_event_types_exist():
    from mage.orchestration.events import EventType
    expected = {
        "INSCRIBE_STARTED",
        "INSCRIBE_COMPLETED",
        "BEHAVIOR_INSCRIBE_STARTED",
        "BEHAVIOR_INSCRIBE_COMPLETED",
        "SCENARIO_DRAFTED",
        "MECHANICAL_PRECHECK_PASSED",
        "MECHANICAL_PRECHECK_FAILED",
        "REVIEWER_VERDICT_RECORDED",
        "REVIEW_AGGREGATE_RECORDED",
        "SCENARIO_APPROVED",
        "SCENARIO_NEEDS_REFACTOR",
        "REVIEW_HALT_PERSISTED",
    }
    actual = {member.name for member in EventType}
    missing = expected - actual
    assert not missing, f"missing event types: {missing}"


def test_plan3_event_type_values():
    from mage.orchestration.events import EventType
    assert EventType.INSCRIBE_STARTED.value == "inscribe_started"
    assert EventType.INSCRIBE_COMPLETED.value == "inscribe_completed"
    assert EventType.BEHAVIOR_INSCRIBE_STARTED.value == "behavior_inscribe_started"
    assert EventType.BEHAVIOR_INSCRIBE_COMPLETED.value == "behavior_inscribe_completed"
    assert EventType.SCENARIO_DRAFTED.value == "scenario_drafted"
    assert EventType.MECHANICAL_PRECHECK_PASSED.value == "mechanical_precheck_passed"
    assert EventType.MECHANICAL_PRECHECK_FAILED.value == "mechanical_precheck_failed"
    assert EventType.REVIEWER_VERDICT_RECORDED.value == "reviewer_verdict_recorded"
    assert EventType.REVIEW_AGGREGATE_RECORDED.value == "review_aggregate_recorded"
    assert EventType.SCENARIO_APPROVED.value == "scenario_approved"
    assert EventType.SCENARIO_NEEDS_REFACTOR.value == "scenario_needs_refactor"
    assert EventType.REVIEW_HALT_PERSISTED.value == "review_halt_persisted"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_events.py::test_plan3_event_types_exist tests/test_events.py::test_plan3_event_type_values -v`
Expected: both FAIL with `AttributeError: type object 'EventType' has no attribute 'INSCRIBE_STARTED'`.

- [ ] **Step 3: Extend the `EventType` enum**

Modify `src/mage/orchestration/events.py`. Append to the `EventType` class after the Plan 5 placeholder comment:

```python
class EventType(str, Enum):
    # Plan 1 — stage lifecycle
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    SCENARIO_STATE_CHANGED = "scenario_state_changed"
    FINDING_RECORDED = "finding_recorded"
    BID_ASSIGNED = "bid_assigned"
    REVERSION_LOGGED = "reversion_logged"
    COSMETIC_REVIEW_QUEUED = "cosmetic_review_queued"
    HUMAN_REVIEW_REQUESTED = "human_review_requested"

    # Plan 2 — Decomposition stage
    DECOMPOSITION_STARTED = "decomposition_started"
    DECOMPOSITION_COMPLETED = "decomposition_completed"

    # Plan 2 — behavior enumeration sub-step
    BEHAVIORS_ENUMERATED = "behaviors_enumerated"

    # Plan 2 — Plan lifecycle
    PLAN_FINALIZED = "plan_finalized"
    PLAN_REVISED = "plan_revised"
    PLAN_DIGEST_MISMATCH = "plan_digest_mismatch"

    # Plan 2 — halt/recovery
    HALT_PERSISTED = "halt_persisted"

    # Plan 5 placeholder (defined here so events log schema is stable)
    BEHAVIORS_REVISED = "behaviors_revised"

    # Plan 3 — Inscribe stage
    INSCRIBE_STARTED = "inscribe_started"
    INSCRIBE_COMPLETED = "inscribe_completed"
    BEHAVIOR_INSCRIBE_STARTED = "behavior_inscribe_started"
    BEHAVIOR_INSCRIBE_COMPLETED = "behavior_inscribe_completed"
    SCENARIO_DRAFTED = "scenario_drafted"
    MECHANICAL_PRECHECK_PASSED = "mechanical_precheck_passed"
    MECHANICAL_PRECHECK_FAILED = "mechanical_precheck_failed"
    REVIEWER_VERDICT_RECORDED = "reviewer_verdict_recorded"
    REVIEW_AGGREGATE_RECORDED = "review_aggregate_recorded"
    SCENARIO_APPROVED = "scenario_approved"
    SCENARIO_NEEDS_REFACTOR = "scenario_needs_refactor"
    REVIEW_HALT_PERSISTED = "review_halt_persisted"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_events.py -v`
Expected: all events tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/events.py tests/test_events.py
git commit -m "feat(orchestration): add 12 Plan 3 EventType members"
```

---

### Task 2: Add `Base85BID.derive(parent, scenario_index)` classmethod

**Files:**
- Modify: `src/mage/artifacts/bid.py`
- Test: `tests/test_bid.py` (Plan 1, extend)

**Interfaces:**
- Consumes: `Base85BID` (Plan 1).
- Produces: `Base85BID.derive(parent: Base85BID, scenario_index: int) -> Base85BID` — returns a sub-BID by appending a Base85-encoded `scenario_index` to the parent's value.

**Derivation rule:** `parent.value` (5 Base85 chars) + `_encode_index(scenario_index)` (one or more Base85 chars). Encode `scenario_index` as the shortest Base85 representation with no leading zeros — i.e., the natural encoding.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bid.py`:

```python
def test_derive_sub_bid_with_index_zero():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00000")
    sub = Base85BID.derive(parent, 0)
    assert sub.value == "00000" + "0"  # parent + '0' = first scenario


def test_derive_sub_bid_with_index_84():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00001")
    sub = Base85BID.derive(parent, 84)
    # index 84 → single char '~' (last in alphabet)
    assert sub.value == "00001~"


def test_derive_sub_bid_with_index_85():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00010")
    sub = Base85BID.derive(parent, 85)
    # index 85 → two chars: "01" (since 85 = 1*85 + 0)
    assert sub.value == "00010" + "10"


def test_derive_sub_bid_rejects_negative_index():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00000")
    import pytest
    with pytest.raises(ValueError, match="non-negative"):
        Base85BID.derive(parent, -1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bid.py::test_derive_sub_bid_with_index_zero tests/test_bid.py::test_derive_sub_bid_with_index_84 tests/test_bid.py::test_derive_sub_bid_with_index_85 tests/test_bid.py::test_derive_sub_bid_rejects_negative_index -v`
Expected: all 4 FAIL with `AttributeError: type object 'Base85BID' has no attribute 'derive'`.

- [ ] **Step 3: Implement `derive()`**

Modify `src/mage/artifacts/bid.py`. Add after the existing `Base85BID` class methods:

```python
@classmethod
def derive(cls, parent: "Base85BID", scenario_index: int) -> "Base85BID":
    """Derive a sub-BID by appending a Base85-encoded scenario_index to parent.

    The result is parent.value + encode_base85(scenario_index). The encoding
    is the shortest natural Base85 representation with no leading zeros
    (i.e., index 0 → "0", index 1 → "1", ..., index 84 → "~", index 85 → "10").
    """
    if scenario_index < 0:
        raise ValueError(f"scenario_index must be non-negative; got {scenario_index}")

    if scenario_index == 0:
        suffix = BASE85_ALPHABET[0]  # "0"
    else:
        # Convert to Base85 with no leading zeros.
        digits: list[int] = []
        n = scenario_index
        while n > 0:
            digits.append(n % BASE85_RADIX)
            n //= BASE85_RADIX
        digits.reverse()
        suffix = "".join(BASE85_ALPHABET[d] for d in digits)

    return cls(value=parent.value + suffix)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bid.py -v`
Expected: all bid tests pass (existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/bid.py tests/test_bid.py
git commit -m "feat(artifacts): add Base85BID.derive for sub-BID assignment"
```

---

### Task 3: Add `MappingArtifact.append_scenario()` helper

**Files:**
- Modify: `src/mage/artifacts/mapping.py`
- Test: `tests/test_mapping.py` (Plan 1+2, extend)

**Interfaces:**
- Consumes: existing `MappingArtifact`, `BaseBIDEntry`, `ScenarioEntry` (Plan 1+2).
- Produces: `MappingArtifact.append_scenario(base_bid: str, scenario: ScenarioEntry) -> MappingArtifact` — returns a new `MappingArtifact` with the scenario appended to the matching `BaseBIDEntry.scenarios`. Raises `BaseBIDNotFoundError` if no entry matches.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mapping.py`:

```python
def test_append_scenario_adds_to_matching_base_bid():
    from mage.artifacts.mapping import (
        BaseBIDEntry, MappingArtifact, ScenarioEntry, LifecycleStatus,
    )
    entry = BaseBIDEntry(
        base_bid="00000",
        behavior_name="Authenticate user",
        behavior_description="User logs in",
    )
    mapping = MappingArtifact(project_id="p", base_bids=[entry])

    new_scenario = ScenarioEntry(
        sub_bid="000000",
        scenario_text_hash="abc123",
        lifecycle_status=LifecycleStatus.APPROVED,
    )
    updated = mapping.append_scenario("00000", new_scenario)

    target = next(e for e in updated.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) == 1
    assert target.scenarios[0].sub_bid == "000000"
    # Original mapping is unchanged (frozen).
    assert mapping.base_bids[0].scenarios == []


def test_append_scenario_raises_on_unknown_base_bid():
    from mage.artifacts.mapping import (
        BaseBIDEntry, MappingArtifact, ScenarioEntry, LifecycleStatus,
    )
    mapping = MappingArtifact(project_id="p", base_bids=[
        BaseBIDEntry(base_bid="00000", behavior_name="x", behavior_description="y"),
    ])
    scenario = ScenarioEntry(
        sub_bid="000000", scenario_text_hash="h", lifecycle_status=LifecycleStatus.APPROVED,
    )
    import pytest
    with pytest.raises(BaseBIDNotFoundError, match="99999"):
        mapping.append_scenario("99999", scenario)
```

Also add to `src/mage/artifacts/mapping.py` (at the top of the file, after the existing imports):

```python
class BaseBIDNotFoundError(Exception):
    """Raised when an operation references a base_bid not in the mapping."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mapping.py::test_append_scenario_adds_to_matching_base_bid tests/test_mapping.py::test_append_scenario_raises_on_unknown_base_bid -v`
Expected: both FAIL with `AttributeError: 'MappingArtifact' object has no attribute 'append_scenario'` (and `NameError: BaseBIDNotFoundError` on second).

- [ ] **Step 3: Implement `append_scenario()` and the exception**

Modify `src/mage/artifacts/mapping.py`. Add the exception class after the existing `ScenarioEntry`:

```python
class BaseBIDNotFoundError(Exception):
    """Raised when an operation references a base_bid not in the mapping."""
```

Add the method to `MappingArtifact`:

```python
def append_scenario(self, base_bid: str, scenario: "ScenarioEntry") -> "MappingArtifact":
    """Return a new MappingArtifact with `scenario` appended to the matching BaseBIDEntry.scenarios.

    Raises BaseBIDNotFoundError if no entry matches.
    """
    new_entries: list[BaseBIDEntry] = []
    matched = False
    for entry in self.base_bids:
        if entry.base_bid == base_bid:
            matched = True
            new_entries.append(
                entry.model_copy(update={"scenarios": [*entry.scenarios, scenario]})
            )
        else:
            new_entries.append(entry)
    if not matched:
        raise BaseBIDNotFoundError(
            f"base_bid {base_bid!r} not found in mapping with project_id={self.project_id!r}"
        )
    return self.model_copy(update={"base_bids": new_entries})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mapping.py -v`
Expected: all mapping tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/mapping.py tests/test_mapping.py
git commit -m "feat(artifacts): add MappingArtifact.append_scenario helper"
```

---

### Task 4: Extend `HostConfig` with `max_iterations` and `enabled_reviewers`

**Files:**
- Modify: `src/mage/verification/host_overrides.py`
- Test: `tests/test_host_overrides.py` (Plan 1+2, extend)

**Interfaces:**
- Consumes: existing `HostConfig` (Plan 1+2).
- Produces: `HostConfig.max_iterations: int = 3` and `HostConfig.enabled_reviewers: list[str] | None = None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_host_overrides.py`:

```python
def test_host_config_max_iterations_default_is_3():
    from mage.verification.host_overrides import HostConfig
    cfg = HostConfig()
    assert cfg.max_iterations == 3


def test_host_config_max_iterations_override():
    from mage.verification.host_overrides import HostConfig
    cfg = HostConfig(max_iterations=5)
    assert cfg.max_iterations == 5


def test_host_config_enabled_reviewers_default_is_none():
    from mage.verification.host_overrides import HostConfig
    cfg = HostConfig()
    assert cfg.enabled_reviewers is None


def test_host_config_enabled_reviewers_override():
    from mage.verification.host_overrides import HostConfig
    cfg = HostConfig(enabled_reviewers=["spec_compliance", "testability"])
    assert cfg.enabled_reviewers == ["spec_compliance", "testability"]


def test_load_host_config_parses_max_iterations(tmp_path):
    import yaml
    from mage.verification.host_overrides import load_host_config
    config_dir = tmp_path / ".haileris"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(yaml.safe_dump({"max_iterations": 7}))
    cfg = load_host_config(tmp_path)
    assert cfg.max_iterations == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_host_overrides.py -v -k "max_iterations or enabled_reviewers"`
Expected: all 5 FAIL with `TypeError: HostConfig.__init__() got an unexpected keyword argument 'max_iterations'`.

- [ ] **Step 3: Add the new fields to `HostConfig`**

Modify `src/mage/verification/host_overrides.py`. Update the `HostConfig` class:

```python
class HostConfig(BaseModel):
    """Parsed host-project configuration."""

    model_config = ConfigDict(frozen=True, extra="allow")

    max_iterations: int = 3  # spec default; Plan 3 addition
    check_set: str = "default"
    require_plan_approval: bool = True
    plan_template_path: Path | None = None
    enabled_reviewers: list[str] | None = None  # Plan 3 addition; None = all enabled
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_host_overrides.py -v`
Expected: all host_overrides tests pass (existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/host_overrides.py tests/test_host_overrides.py
git commit -m "feat(verification): add max_iterations + enabled_reviewers to HostConfig"
```

---

### Task 5: Add `ScenarioSpec` model

**Files:**
- Create: `src/mage/agents/inscribe.py`
- Test: `tests/test_inscribe_models.py` (Plan 3 NEW)

**Interfaces:**
- Consumes: Pydantic v2, frozen config.
- Produces: `ScenarioSpec(BaseModel)` with `name`, `gherkin_body`, `tags`, `notes`, `cross_behavior_tags`. Also defines `InscribeOutput` (wrapper around `list[ScenarioSpec]`).

- [ ] **Step 1: Create the failing test file**

Create `tests/test_inscribe_models.py`:

```python
"""Tests for Inscribe agent models."""


def test_scenario_spec_minimal():
    from mage.agents.inscribe import ScenarioSpec
    spec = ScenarioSpec(name="login succeeds", gherkin_body="Given ...")
    assert spec.name == "login succeeds"
    assert spec.gherkin_body == "Given ..."
    assert spec.tags == []
    assert spec.notes == ""
    assert spec.cross_behavior_tags == []


def test_scenario_spec_with_all_fields():
    from mage.agents.inscribe import ScenarioSpec
    spec = ScenarioSpec(
        name="register duplicate email fails",
        gherkin_body="Given a registered email\nWhen register\nThen fail",
        tags=["@auth", "@negative"],
        notes="Edge case; needs user-fixture cleanup.",
        cross_behavior_tags=["00000@authenticate-user"],
    )
    assert spec.tags == ["@auth", "@negative"]
    assert spec.cross_behavior_tags == ["00000@authenticate-user"]


def test_scenario_spec_is_frozen():
    from mage.agents.inscribe import ScenarioSpec
    spec = ScenarioSpec(name="x", gherkin_body="y")
    import pytest
    with pytest.raises(Exception):  # ValidationError or AttributeError
        spec.name = "mutated"


def test_inscribe_output_holds_scenarios():
    from mage.agents.inscribe import InscribeOutput, ScenarioSpec
    scenarios = [
        ScenarioSpec(name="a", gherkin_body="A"),
        ScenarioSpec(name="b", gherkin_body="B"),
    ]
    output = InscribeOutput(scenarios=scenarios)
    assert len(output.scenarios) == 2
    assert output.scenarios[0].name == "a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_inscribe_models.py -v`
Expected: import error — `tests/test_inscribe_models.py` cannot import `mage.agents.inscribe` (file does not exist).

- [ ] **Step 3: Create the models file**

Create `src/mage/agents/inscribe.py`:

```python
"""Inscribe agent: Pydantic-AI agent that drafts scenarios from behavior specs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScenarioSpec(BaseModel):
    """A single scenario drafted by the Inscribe agent.

    Sub-BID and scenario_text_hash are NOT assigned here — they are assigned
    by the InscribeStage at the moment the scenario transitions to APPROVED.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    gherkin_body: str
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    cross_behavior_tags: list[str] = Field(default_factory=list)


class InscribeOutput(BaseModel):
    """Combined output of the Inscribe agent for one behavior."""

    model_config = ConfigDict(frozen=True)

    scenarios: list[ScenarioSpec]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_inscribe_models.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/agents/inscribe.py tests/test_inscribe_models.py
git commit -m "feat(agents): add Inscribe ScenarioSpec + InscribeOutput models"
```

---

### Task 6: `VerdictArtifact` schemas (Pydantic models only)

**Files:**
- Create: `src/mage/artifacts/verdict.py`
- Test: `tests/test_verdict.py` (Plan 3 NEW)

**Interfaces:**
- Consumes: Pydantic v2, frozen config.
- Produces: `ReviewerVerdict`, `ReviewerFinding`, `DimensionSummary`, `ReviewerAggregate` Pydantic models (no I/O yet; that's Task 7).

- [ ] **Step 1: Write the failing test**

Create `tests/test_verdict.py`:

```python
"""Tests for verdict schemas (no I/O yet)."""


def test_reviewer_finding_minimal():
    from mage.artifacts.verdict import ReviewerFinding
    f = ReviewerFinding(
        id="f-001",
        severity="critical",
        location="line 5",
        issue="Given uses imperative verb",
        rationale="'Type' is an imperative, not declarative phrasing.",
        suggestion="Replace with: Given the user is on the login form",
    )
    assert f.severity == "critical"
    assert f.citations == []  # default


def test_reviewer_verdict_pass_with_no_findings():
    from mage.artifacts.verdict import ReviewerVerdict
    from datetime import datetime, UTC
    v = ReviewerVerdict(
        dimension="spec_compliance",
        outcome="pass",
        draft_hash="abc123",
        reviewed_at=datetime.now(UTC),
        reviewer_id="spec_compliance@v1",
    )
    assert v.dimension == "spec_compliance"
    assert v.outcome == "pass"
    assert v.findings == []


def test_reviewer_verdict_fail_with_findings():
    from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
    from datetime import datetime, UTC
    findings = [
        ReviewerFinding(
            id="f-1",
            severity="major",
            location="line 7",
            issue="ambiguous step",
            rationale="'it' has no clear antecedent.",
        ),
    ]
    v = ReviewerVerdict(
        dimension="scenario_clarity",
        outcome="fail",
        draft_hash="def456",
        reviewed_at=datetime.now(UTC),
        reviewer_id="scenario_clarity@v1",
        findings=findings,
    )
    assert v.outcome == "fail"
    assert len(v.findings) == 1
    assert v.findings[0].rationale == "'it' has no clear antecedent."


def test_reviewer_finding_requires_rationale():
    from mage.artifacts.verdict import ReviewerFinding
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewerFinding(
            id="f-1",
            severity="minor",
            location="line 1",
            issue="x",
            rationale="",  # empty
        )


def test_reviewer_verdict_outcome_literal():
    from mage.artifacts.verdict import ReviewerVerdict
    from datetime import datetime, UTC
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewerVerdict(
            dimension="d",
            outcome="maybe",  # invalid literal
            draft_hash="h",
            reviewed_at=datetime.now(UTC),
            reviewer_id="d@v1",
        )


def test_dimension_summary():
    from mage.artifacts.verdict import DimensionSummary
    s = DimensionSummary(
        outcome="pass",
        reviewer_verdict_ref=".haileris/verdicts/abc/spec_compliance.yaml",
        findings_count=0,
    )
    assert s.outcome == "pass"


def test_reviewer_aggregate_all_pass_yields_approved():
    from mage.artifacts.verdict import ReviewerAggregate, DimensionSummary
    from datetime import datetime, UTC
    per_dim = {
        d: DimensionSummary(outcome="pass", reviewer_verdict_ref=f"{d}.yaml", findings_count=0)
        for d in ["spec_compliance", "scenario_clarity", "step_grammar",
                  "testability", "determinism", "naming_idiom", "lifecycle_tags"]
    }
    agg = ReviewerAggregate(
        draft_hash="h",
        aggregated_at=datetime.now(UTC),
        iteration=1,
        per_dimension=per_dim,
        decision="approved",
        reasoning="all 7 dimensions passed",
    )
    assert agg.decision == "approved"
    assert len(agg.per_dimension) == 7


def test_reviewer_aggregate_decision_literal():
    from mage.artifacts.verdict import ReviewerAggregate
    from datetime import datetime, UTC
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewerAggregate(
            draft_hash="h",
            aggregated_at=datetime.now(UTC),
            iteration=1,
            per_dimension={},
            decision="weird",  # invalid literal
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: import error — `tests/test_verdict.py` cannot import `mage.artifacts.verdict`.

- [ ] **Step 3: Create the verdict schemas file**

Create `src/mage/artifacts/verdict.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/verdict.py tests/test_verdict.py
git commit -m "feat(artifacts): add verdict schemas (ReviewerVerdict, ReviewerAggregate)"
```

---

### Task 7: `VerdictArtifact.finalize/load/revise` (digest-pinned, mirrors PlanArtifact)

**Files:**
- Modify: `src/mage/artifacts/verdict.py`
- Test: `tests/test_verdict.py` (extend)

**Interfaces:**
- Consumes: `ReviewerVerdict`, `ReviewerAggregate`, `EventsLog`, `EventType` (Plan 1+2 + Task 1).
- Produces: `VerdictArtifact.finalize(path, model, events_log) -> str` (writes YAML, computes digest, emits `REVIEWER_VERDICT_RECORDED` or `REVIEW_AGGREGATE_RECORDED`); `VerdictArtifact.load(path, events_log) -> BaseModel` (digest-verified read).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_verdict.py`:

```python
def test_verdict_artifact_finalize_writes_yaml_and_emits_event(tmp_path):
    from mage.artifacts.verdict import VerdictArtifact, ReviewerVerdict
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    verdict = ReviewerVerdict(
        dimension="spec_compliance",
        outcome="pass",
        draft_hash="abc",
        reviewed_at=datetime.now(UTC),
        reviewer_id="spec_compliance@v1",
    )
    path = tmp_path / ".haileris" / "verdicts" / "abc" / "spec_compliance.yaml"
    digest = VerdictArtifact.finalize(path, verdict, log)

    assert path.exists()
    assert len(digest) == 64  # sha256 hex
    events = log.read_all()
    assert any(e.event_type.value == "reviewer_verdict_recorded" for e in events)


def test_verdict_artifact_load_returns_model_when_digest_matches(tmp_path):
    from mage.artifacts.verdict import VerdictArtifact, ReviewerVerdict
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    verdict = ReviewerVerdict(
        dimension="d",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="d@v1",
    )
    path = tmp_path / "v.yaml"
    VerdictArtifact.finalize(path, verdict, log)
    loaded = VerdictArtifact.load(path, log)
    assert isinstance(loaded, ReviewerVerdict)
    assert loaded.dimension == "d"


def test_verdict_artifact_load_raises_on_digest_mismatch(tmp_path):
    from mage.artifacts.verdict import VerdictArtifact, ReviewerVerdict, VerdictDigestMismatchError
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    verdict = ReviewerVerdict(
        dimension="d",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="d@v1",
    )
    path = tmp_path / "v.yaml"
    VerdictArtifact.finalize(path, verdict, log)
    # Tamper with the file
    path.write_text("tampered: yes\n")
    import pytest
    with pytest.raises(VerdictDigestMismatchError):
        VerdictArtifact.load(path, log)


def test_verdict_artifact_finalize_aggregate_uses_aggregate_event(tmp_path):
    from mage.artifacts.verdict import (
        VerdictArtifact, ReviewerAggregate, DimensionSummary,
    )
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    agg = ReviewerAggregate(
        draft_hash="x",
        aggregated_at=datetime.now(UTC),
        iteration=1,
        per_dimension={
            "spec_compliance": DimensionSummary(
                outcome="pass", reviewer_verdict_ref="r.yaml", findings_count=0
            ),
        },
        decision="approved",
    )
    path = tmp_path / "agg.yaml"
    VerdictArtifact.finalize(path, agg, log)
    events = log.read_all()
    assert any(e.event_type.value == "review_aggregate_recorded" for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_verdict.py -v -k "verdict_artifact"`
Expected: all 4 FAIL with `AttributeError: module 'mage.artifacts.verdict' has no attribute 'VerdictArtifact'` or `VerdictDigestMismatchError`.

- [ ] **Step 3: Implement `VerdictArtifact` and the digest-mismatch exception**

Modify `src/mage/artifacts/verdict.py`. Append to the end of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: all verdict tests pass (existing + 4 new = 12).

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/verdict.py tests/test_verdict.py
git commit -m "feat(artifacts): add VerdictArtifact with digest-pinned finalize/load"
```

---

### Task 8: `ReviewerAgent` base class

**Files:**
- Create: `src/mage/verification/reviewers/__init__.py`
- Create: `src/mage/verification/reviewers/base.py`
- Test: `tests/test_reviewers/__init__.py` (empty)
- Test: `tests/test_reviewers/test_base.py` (Plan 3 NEW)

**Interfaces:**
- Consumes: Pydantic-AI, `ReviewerVerdict`, `ScenarioSpec`, `MappingArtifact` (Plan 1+2 + Task 5 + Task 6).
- Produces: `ReviewerAgent` ABC with `dimension: str`, `_system_prompt() -> str` abstract method, and `run(draft, spec_context) -> ReviewerVerdict` concrete method that runs Pydantic-AI and persists via `VerdictArtifact`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/__init__.py` (empty file).

Create `tests/test_reviewers/test_base.py`:

```python
"""Tests for ReviewerAgent base class."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import ClassVar

import pytest
from pydantic_ai import models as pydantic_ai_models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.base import ReviewerAgent


class FakeReviewer(ReviewerAgent):
    dimension = "fake_dimension"

    def _system_prompt(self) -> str:
        return "You are a fake reviewer."


@pytest.fixture
def fake_reviewer():
    # Use Pydantic-AI TestModel for deterministic tests.
    return FakeReviewer(model=TestModel(custom_output_args=None))


def test_reviewer_agent_has_dimension_attribute():
    assert FakeReviewer.dimension == "fake_dimension"


def test_reviewer_agent_run_returns_reviewerverdict(tmp_path, fake_reviewer):
    from mage.artifacts.verdict import VerdictArtifact

    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = fake_reviewer.run(
        draft=draft,
        spec_context={"behavior_name": "auth", "behavior_description": "log in"},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "fake_dimension"
    assert verdict.outcome in ("pass", "fail")
    assert verdict.reviewer_id == "fake_dimension@v1"


def test_reviewer_agent_run_persists_verdict(tmp_path, fake_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")
    path = tmp_path / "v.yaml"

    fake_reviewer.run(
        draft=draft,
        spec_context={},
        mapping=mapping,
        events_log=log,
        verdict_path=path,
    )
    # Verdict was finalized → file exists, event emitted
    assert path.exists()
    events = log.read_all()
    assert any(e.event_type.value == "reviewer_verdict_recorded" for e in events)


def test_reviewer_agent_requires_dimension():
    class BrokenReviewer(ReviewerAgent):
        def _system_prompt(self) -> str:
            return "x"
    with pytest.raises(ValueError, match="dimension"):
        BrokenReviewer(model=TestModel())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_base.py -v`
Expected: import error — `mage.verification.reviewers.base` does not exist.

- [ ] **Step 3: Create the base class**

Create `src/mage/verification/reviewers/__init__.py` (empty file).

Create `src/mage/verification/reviewers/base.py`:

```python
"""ReviewerAgent base class — shared scaffolding for the 7 reviewer dimensions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import (
    ReviewerFinding,
    ReviewerVerdict,
    VerdictArtifact,
)
from mage.orchestration.events import EventsLog


class ReviewerAgent(ABC):
    """Base class for the 7 reviewer dimensions.

    Subclasses must define `dimension` (str) and implement `_system_prompt()`.
    The shared `run()` method:
    - hashes the draft + spec context into `draft_hash`
    - calls Pydantic-AI to emit a ReviewerVerdict
    - persists via VerdictArtifact.finalize(verdict_path, ...)
    """

    dimension: ClassVar[str] = ""

    def __init__(self, model) -> None:
        if not self.dimension:
            raise ValueError(f"{type(self).__name__} must define `dimension`")
        self._agent: Agent[None, ReviewerVerdict] = Agent(
            model,
            output_type=ReviewerVerdict,
            system_prompt=self._system_prompt(),
        )

    @abstractmethod
    def _system_prompt(self) -> str:
        """Return the dimension-specific rubric and examples."""
        ...

    def _compute_draft_hash(self, draft: ScenarioSpec, spec_context: dict[str, Any]) -> str:
        """Compute a stable hash from draft + spec context."""
        import hashlib
        import json
        payload = json.dumps(
            {"draft": draft.model_dump(mode="json"), "spec_context": spec_context},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def run(
        self,
        *,
        draft: ScenarioSpec,
        spec_context: dict[str, Any],
        mapping: MappingArtifact,
        events_log: EventsLog,
        verdict_path: Path,
    ) -> ReviewerVerdict:
        """Run the reviewer against the draft and persist the verdict."""
        draft_hash = self._compute_draft_hash(draft, spec_context)

        prompt = (
            f"Draft scenario:\n{draft.model_dump_json(indent=2)}\n\n"
            f"Spec context:\n{json.dumps(spec_context, indent=2, default=str)}"
        )
        result = self._agent.run_sync(prompt).output

        # Force the dimension + draft_hash into the result (don't trust the agent).
        result_dict = result.model_dump()
        result_dict["dimension"] = self.dimension
        result_dict["draft_hash"] = draft_hash
        result_dict["reviewed_at"] = datetime.now(UTC)
        result_dict["reviewer_id"] = f"{self.dimension}@v1"
        finalized = ReviewerVerdict.model_validate(result_dict)

        VerdictArtifact.finalize(verdict_path, finalized, events_log)
        return finalized
```

Add the `import json` and `from typing import ClassVar` imports if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_base.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers tests/test_reviewers
git commit -m "feat(reviewers): add ReviewerAgent base class"
```

---

### Task 9: Add `spec_compliance` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/spec_compliance.py`
- Test: `tests/test_reviewers/test_spec_compliance.py`

**Interfaces:**
- Consumes: `ReviewerAgent` (Task 8).
- Produces: `SpecComplianceReviewer(dimension="spec_compliance")` with rubric covering behavior spec match + depends_on + cross_behavior_links.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_spec_compliance.py`:

```python
"""Tests for the spec_compliance reviewer."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer


def test_dimension_is_spec_compliance():
    assert SpecComplianceReviewer.dimension == "spec_compliance"


def test_run_emits_reviewerverdict(tmp_path):
    reviewer = SpecComplianceReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="login", gherkin_body="Given ...")

    verdict = reviewer.run(
        draft=draft,
        spec_context={"behavior_name": "auth", "behavior_description": "log in"},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "spec_compliance"
    assert verdict.outcome in ("pass", "fail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_spec_compliance.py -v`
Expected: import error — `mage.verification.reviewers.spec_compliance` does not exist.

- [ ] **Step 3: Implement `SpecComplianceReviewer`**

Create `src/mage/verification/reviewers/spec_compliance.py`:

```python
"""spec_compliance reviewer — does the scenario implement the behavior spec?"""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class SpecComplianceReviewer(ReviewerAgent):
    """Checks whether the drafted scenario implements the parent behavior spec.

    Rubric:
    - Scenario's `gherkin_body` should cover the behavior's description.
    - `depends_on` should be honored (no scenario implementing behavior X
      before behavior Y when X depends_on Y).
    - `cross_behavior_links` should be reflected in tags or step bodies.
    """

    dimension = "spec_compliance"

    def _system_prompt(self) -> str:
        return (
            "You are the spec_compliance reviewer for HAILERIS v2.\n\n"
            "Evaluate whether the drafted scenario implements the parent behavior spec.\n"
            "Check:\n"
            "1. The Given/When/Then covers the behavior's description.\n"
            "2. depends_on is honored (scenario doesn't implement a behavior "
            "   before its dependencies).\n"
            "3. cross_behavior_links are referenced via tags or step bodies.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include "
            "findings with severity (critical/major/minor), location, issue, "
            "rationale (mandatory), and suggestion."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_spec_compliance.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/spec_compliance.py tests/test_reviewers/test_spec_compliance.py
git commit -m "feat(reviewers): add spec_compliance reviewer"
```

---

### Task 10: Add `scenario_clarity` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/scenario_clarity.py`
- Test: `tests/test_reviewers/test_scenario_clarity.py`

**Interfaces:**
- Consumes: `ReviewerAgent` (Task 8).
- Produces: `ScenarioClarityReviewer(dimension="scenario_clarity")`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_scenario_clarity.py`:

```python
"""Tests for the scenario_clarity reviewer."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer


def test_dimension_is_scenario_clarity():
    assert ScenarioClarityReviewer.dimension == "scenario_clarity"


def test_run_emits_reviewerverdict(tmp_path):
    reviewer = ScenarioClarityReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="login", gherkin_body="Given ...")

    verdict = reviewer.run(
        draft=draft,
        spec_context={"behavior_name": "auth"},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "scenario_clarity"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_scenario_clarity.py -v`
Expected: import error — `mage.verification.reviewers.scenario_clarity` does not exist.

- [ ] **Step 3: Implement `ScenarioClarityReviewer`**

Create `src/mage/verification/reviewers/scenario_clarity.py`:

```python
"""scenario_clarity reviewer — is the Given/When/Then readable and single-intent?"""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class ScenarioClarityReviewer(ReviewerAgent):
    """Checks whether the scenario is clearly written and single-intent.

    Rubric:
    - Each step is short and unambiguous.
    - Single intent: scenario tests one thing, not multiple.
    - No wandering prose; scenario is concise.
    - Pronouns ('it', 'they') have clear antecedents.
    """

    dimension = "scenario_clarity"

    def _system_prompt(self) -> str:
        return (
            "You are the scenario_clarity reviewer for HAILERIS v2.\n\n"
            "Evaluate the Given/When/Then scenario for clarity and single intent.\n"
            "Check:\n"
            "1. Each step is short, unambiguous, and free of pronouns with unclear antecedents.\n"
            "2. Single intent — scenario tests one thing, not multiple behaviors.\n"
            "3. No wandering prose; scenario is concise.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include "
            "findings with severity, location, issue, rationale (mandatory), suggestion."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_scenario_clarity.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/scenario_clarity.py tests/test_reviewers/test_scenario_clarity.py
git commit -m "feat(reviewers): add scenario_clarity reviewer"
```

---

### Task 11: Add `step_grammar` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/step_grammar.py`
- Test: `tests/test_reviewers/test_step_grammar.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_step_grammar.py`:

```python
"""Tests for the step_grammar reviewer."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.step_grammar import StepGrammarReviewer


def test_dimension_is_step_grammar():
    assert StepGrammarReviewer.dimension == "step_grammar"


def test_run_returns_verdict(tmp_path):
    reviewer = StepGrammarReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = reviewer.run(
        draft=draft, spec_context={}, mapping=mapping,
        events_log=log, verdict_path=tmp_path / "v.yaml",
    )
    assert verdict.dimension == "step_grammar"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_step_grammar.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

Create `src/mage/verification/reviewers/step_grammar.py`:

```python
"""step_grammar reviewer — declarative phrasing, no imperative leakage."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class StepGrammarReviewer(ReviewerAgent):
    """Checks whether steps use declarative phrasing.

    Rubric:
    - Steps use 3rd-person present tense, not imperative ("click", "type").
    - Steps reuse defined steps where applicable.
    - No UI-control language (click, drag, hover) in non-UI scenarios.
    """

    dimension = "step_grammar"

    def _system_prompt(self) -> str:
        return (
            "You are the step_grammar reviewer for HAILERIS v2.\n\n"
            "Evaluate the Given/When/Then steps for declarative phrasing.\n"
            "Check:\n"
            "1. No imperative verbs (click, type, drag, hover) unless the scenario "
            "   is explicitly UI-driven.\n"
            "2. Steps are written in 3rd-person present tense.\n"
            "3. Steps reuse defined step patterns where applicable.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_step_grammar.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/step_grammar.py tests/test_reviewers/test_step_grammar.py
git commit -m "feat(reviewers): add step_grammar reviewer"
```

---

### Task 12: Add `testability` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/testability.py`
- Test: `tests/test_reviewers/test_testability.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_testability.py`:

```python
"""Tests for the testability reviewer."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.testability import TestabilityReviewer


def test_dimension_is_testability():
    assert TestabilityReviewer.dimension == "testability"


def test_run_returns_verdict(tmp_path):
    reviewer = TestabilityReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = reviewer.run(
        draft=draft, spec_context={}, mapping=mapping,
        events_log=log, verdict_path=tmp_path / "v.yaml",
    )
    assert verdict.dimension == "testability"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_testability.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

Create `src/mage/verification/reviewers/testability.py`:

```python
"""testability reviewer — can the scenario become a red/green unit test?"""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class TestabilityReviewer(ReviewerAgent):
    """Checks whether the scenario can be implemented as a unit test.

    Rubric:
    - Each step is observable (has a clear assertion target).
    - No hidden coupling (assertions don't depend on undocumented state).
    - Steps can be implemented as function calls or method invocations.
    - Failure modes are explicit.
    """

    dimension = "testability"

    def _system_prompt(self) -> str:
        return (
            "You are the testability reviewer for HAILERIS v2.\n\n"
            "Evaluate whether the Given/When/Then scenario can be implemented as "
            "a red/green unit test.\n"
            "Check:\n"
            "1. Each step is observable — has a clear assertion target.\n"
            "2. No hidden coupling — assertions don't depend on undocumented state.\n"
            "3. Steps can be implemented as function calls or method invocations.\n"
            "4. Failure modes are explicit (you can tell when the scenario fails).\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_testability.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/testability.py tests/test_reviewers/test_testability.py
git commit -m "feat(reviewers): add testability reviewer"
```

---

### Task 13: Add `determinism` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/determinism.py`
- Test: `tests/test_reviewers/test_determinism.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_determinism.py`:

```python
"""Tests for the determinism reviewer."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.determinism import DeterminismReviewer


def test_dimension_is_determinism():
    assert DeterminismReviewer.dimension == "determinism"


def test_run_returns_verdict(tmp_path):
    reviewer = DeterminismReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = reviewer.run(
        draft=draft, spec_context={}, mapping=mapping,
        events_log=log, verdict_path=tmp_path / "v.yaml",
    )
    assert verdict.dimension == "determinism"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_determinism.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

Create `src/mage/verification/reviewers/determinism.py`:

```python
"""determinism reviewer — no I/O, time, randomness outside fixtures."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class DeterminismReviewer(ReviewerAgent):
    """Checks whether the scenario is deterministic and replayable.

    Rubric:
    - No unseeded randomness.
    - No wall-clock time dependencies (use injected clock).
    - No I/O outside fixtures (filesystem, network, DB).
    - Output is fully determined by inputs.
    """

    dimension = "determinism"

    def _system_prompt(self) -> str:
        return (
            "You are the determinism reviewer for HAILERIS v2.\n\n"
            "Evaluate whether the Given/When/Then scenario is deterministic and replayable.\n"
            "Check:\n"
            "1. No unseeded randomness (random.choice, random.random without seed).\n"
            "2. No wall-clock time dependencies (datetime.now() without injection).\n"
            "3. No I/O outside fixtures (filesystem, network, DB calls without setup).\n"
            "4. Output is fully determined by inputs.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_determinism.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/determinism.py tests/test_reviewers/test_determinism.py
git commit -m "feat(reviewers): add determinism reviewer"
```

---

### Task 14: Add `naming_idiom` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/naming_idiom.py`
- Test: `tests/test_reviewers/test_naming_idiom.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_naming_idiom.py`:

```python
"""Tests for the naming_idiom reviewer."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer


def test_dimension_is_naming_idiom():
    assert NamingIdiomReviewer.dimension == "naming_idiom"


def test_run_returns_verdict(tmp_path):
    reviewer = NamingIdiomReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="login_succeeds", gherkin_body="Given y")

    verdict = reviewer.run(
        draft=draft, spec_context={}, mapping=mapping,
        events_log=log, verdict_path=tmp_path / "v.yaml",
    )
    assert verdict.dimension == "naming_idiom"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_naming_idiom.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

Create `src/mage/verification/reviewers/naming_idiom.py`:

```python
"""naming_idiom reviewer — scenario names + tags follow host conventions."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class NamingIdiomReviewer(ReviewerAgent):
    """Checks whether scenario names and tags follow host conventions.

    Rubric:
    - Scenario name uses kebab-case or snake_case (project-defined).
    - Tag names use kebab-case.
    - Tag vocabulary matches existing tags (no made-up domains).
    - Scenario name is concise and descriptive.
    """

    dimension = "naming_idiom"

    def _system_prompt(self) -> str:
        return (
            "You are the naming_idiom reviewer for HAILERIS v2.\n\n"
            "Evaluate whether scenario names and tags follow host project conventions.\n"
            "Check:\n"
            "1. Scenario name uses kebab-case or snake_case as appropriate.\n"
            "2. Tag names use kebab-case.\n"
            "3. Tag vocabulary matches existing registered tags (no made-up domains).\n"
            "4. Scenario name is concise (5-10 words) and descriptive.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_naming_idiom.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/naming_idiom.py tests/test_reviewers/test_naming_idiom.py
git commit -m "feat(reviewers): add naming_idiom reviewer"
```

---

### Task 15: Add `lifecycle_tags` reviewer

**Files:**
- Create: `src/mage/verification/reviewers/lifecycle_tags.py`
- Test: `tests/test_reviewers/test_lifecycle_tags.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_lifecycle_tags.py`:

```python
"""Tests for the lifecycle_tags reviewer."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer


def test_dimension_is_lifecycle_tags():
    assert LifecycleTagsReviewer.dimension == "lifecycle_tags"


def test_run_returns_verdict(tmp_path):
    reviewer = LifecycleTagsReviewer(model=TestModel(custom_output_args=None))
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = reviewer.run(
        draft=draft, spec_context={}, mapping=mapping,
        events_log=log, verdict_path=tmp_path / "v.yaml",
    )
    assert verdict.dimension == "lifecycle_tags"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_lifecycle_tags.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

Create `src/mage/verification/reviewers/lifecycle_tags.py`:

```python
"""lifecycle_tags reviewer — required status, sub-bid, cross-behavior tags present."""

from __future__ import annotations

from mage.verification.reviewers.base import ReviewerAgent


class LifecycleTagsReviewer(ReviewerAgent):
    """Checks whether required lifecycle tags are present and well-formed.

    Rubric:
    - @status tag present (one of: inscribing, approved, live, deprecated, retired).
    - @sub-bid tag present and matches Base85BID.derive(parent, index).
    - @cross-behavior-* tags present for each declared cross_behavior_link.
    - Tags are well-formed (no spaces, kebab-case).
    """

    dimension = "lifecycle_tags"

    def _system_prompt(self) -> str:
        return (
            "You are the lifecycle_tags reviewer for HAILERIS v2.\n\n"
            "Evaluate whether required lifecycle tags are present and well-formed.\n"
            "Check:\n"
            "1. @status tag present (inscribing/approved/live/deprecated/retired).\n"
            "2. @sub-bid tag present and well-formed (Base85-encoded).\n"
            "3. @cross-behavior-* tags present for each declared cross_behavior_link.\n"
            "4. Tags are well-formed: kebab-case, no spaces.\n\n"
            "Emit a ReviewerVerdict with outcome=pass or fail. On fail, include findings."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_lifecycle_tags.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/lifecycle_tags.py tests/test_reviewers/test_lifecycle_tags.py
git commit -m "feat(reviewers): add lifecycle_tags reviewer"
```

---

### Task 16: Reviewer registry and 7-reviewer aggregation logic

**Files:**
- Create: `src/mage/verification/reviewers/registry.py`
- Test: `tests/test_reviewers/test_registry.py`

**Interfaces:**
- Consumes: 7 reviewer classes (Tasks 9–15), `ReviewerVerdict`, `ReviewerAggregate`, `DimensionSummary` (Tasks 6+7), `HostConfig` (Task 4).
- Produces: `default_reviewer_registry() -> dict[str, type[ReviewerAgent]]` and `aggregate_verdicts(per_dimension_verdicts: dict[str, ReviewerVerdict], iteration: int) -> ReviewerAggregate`.

**Aggregation rule:** all 7 dimensions `pass` → `approved`; any `fail` → `needs_refactor` (decision-gate stage compares iteration against `max_iterations` to determine `needs_human_review`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewers/test_registry.py`:

```python
"""Tests for reviewer registry + aggregation logic."""

from __future__ import annotations

from datetime import datetime, UTC

from mage.artifacts.verdict import (
    DimensionSummary,
    ReviewerAggregate,
    ReviewerFinding,
    ReviewerVerdict,
)
from mage.verification.reviewers.registry import (
    aggregate_verdicts,
    default_reviewer_registry,
)


def test_default_registry_has_all_7_dimensions():
    registry = default_reviewer_registry()
    expected = {
        "spec_compliance",
        "scenario_clarity",
        "step_grammar",
        "testability",
        "determinism",
        "naming_idiom",
        "lifecycle_tags",
    }
    assert set(registry.keys()) == expected


def test_aggregate_all_pass_yields_approved():
    verdicts = {
        d: ReviewerVerdict(
            dimension=d, outcome="pass", draft_hash="h",
            reviewed_at=datetime.now(UTC), reviewer_id=f"{d}@v1",
        )
        for d in default_reviewer_registry().keys()
    }
    agg = aggregate_verdicts(verdicts, iteration=1)
    assert isinstance(agg, ReviewerAggregate)
    assert agg.decision == "approved"
    assert all(s.outcome == "pass" for s in agg.per_dimension.values())


def test_aggregate_any_fail_yields_needs_refactor():
    verdicts = {
        d: ReviewerVerdict(
            dimension=d, outcome="pass", draft_hash="h",
            reviewed_at=datetime.now(UTC), reviewer_id=f"{d}@v1",
        )
        for d in default_reviewer_registry().keys()
    }
    verdicts["scenario_clarity"] = ReviewerVerdict(
        dimension="scenario_clarity", outcome="fail", draft_hash="h",
        reviewed_at=datetime.now(UTC), reviewer_id="scenario_clarity@v1",
        findings=[
            ReviewerFinding(
                id="f-1", severity="major", location="line 3",
                issue="ambiguous step", rationale="'it' has no antecedent.",
            ),
        ],
    )
    agg = aggregate_verdicts(verdicts, iteration=1)
    assert agg.decision == "needs_refactor"
    assert agg.per_dimension["scenario_clarity"].findings_count == 1
    assert agg.per_dimension["spec_compliance"].outcome == "pass"


def test_aggregate_stores_findings_count():
    verdicts = {
        d: ReviewerVerdict(
            dimension=d, outcome="fail", draft_hash="h",
            reviewed_at=datetime.now(UTC), reviewer_id=f"{d}@v1",
            findings=[
                ReviewerFinding(
                    id="f-1", severity="minor", location="line 1",
                    issue="x", rationale="y",
                ),
                ReviewerFinding(
                    id="f-2", severity="minor", location="line 2",
                    issue="x", rationale="y",
                ),
            ],
        )
        for d in default_reviewer_registry().keys()
    }
    agg = aggregate_verdicts(verdicts, iteration=1)
    assert all(s.findings_count == 2 for s in agg.per_dimension.values())
    assert agg.decision == "needs_refactor"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reviewers/test_registry.py -v`
Expected: import error — `mage.verification.reviewers.registry` does not exist.

- [ ] **Step 3: Implement registry and aggregator**

Create `src/mage/verification/reviewers/registry.py`:

```python
"""Reviewer registry + verdict aggregation logic."""

from __future__ import annotations

from datetime import datetime, UTC

from mage.artifacts.verdict import (
    DimensionSummary,
    ReviewerAggregate,
    ReviewerVerdict,
)
from mage.verification.reviewers.base import ReviewerAgent
from mage.verification.reviewers.determinism import DeterminismReviewer
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
from mage.verification.reviewers.step_grammar import StepGrammarReviewer
from mage.verification.reviewers.testability import TestabilityReviewer


def default_reviewer_registry() -> dict[str, type[ReviewerAgent]]:
    """Return the 7 reviewer dimensions → their agent classes."""
    return {
        "spec_compliance": SpecComplianceReviewer,
        "scenario_clarity": ScenarioClarityReviewer,
        "step_grammar": StepGrammarReviewer,
        "testability": TestabilityReviewer,
        "determinism": DeterminismReviewer,
        "naming_idiom": NamingIdiomReviewer,
        "lifecycle_tags": LifecycleTagsReviewer,
    }


def aggregate_verdicts(
    per_dimension_verdicts: dict[str, ReviewerVerdict],
    iteration: int,
) -> ReviewerAggregate:
    """Aggregate per-dimension verdicts into a single ReviewerAggregate.

    Decision rule:
    - all 7 dimensions pass → 'approved'
    - any dimension fails → 'needs_refactor'
    """
    per_dimension: dict[str, DimensionSummary] = {}
    any_fail = False
    for dimension, verdict in per_dimension_verdicts.items():
        if verdict.outcome == "fail":
            any_fail = True
        per_dimension[dimension] = DimensionSummary(
            outcome=verdict.outcome,
            reviewer_verdict_ref=f".haileris/verdicts/{verdict.draft_hash}/{verdict.dimension}.yaml",
            findings_count=len(verdict.findings),
        )

    decision = "needs_refactor" if any_fail else "approved"
    reasoning = (
        f"all 7 dimensions passed" if decision == "approved"
        else f"at least one dimension failed; iteration={iteration}"
    )

    # The aggregate uses the first verdict's draft_hash (they should all match).
    draft_hash = next(iter(per_dimension_verdicts.values())).draft_hash

    return ReviewerAggregate(
        draft_hash=draft_hash,
        aggregated_at=datetime.now(UTC),
        iteration=iteration,
        per_dimension=per_dimension,
        decision=decision,
        reasoning=reasoning,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reviewers/test_registry.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/reviewers/registry.py tests/test_reviewers/test_registry.py
git commit -m "feat(reviewers): add registry + aggregation logic"
```

---

### Task 17: `InscribeAgent` with Pydantic-AI structured output

**Files:**
- Modify: `src/mage/agents/inscribe.py`
- Test: `tests/test_inscribe_agent.py` (Plan 3 NEW)

**Interfaces:**
- Consumes: `ScenarioSpec`, `InscribeOutput` (Task 5), `AscertainOutput` (Plan 2), `MappingArtifact`, `BaseBIDEntry` (Plan 1+2).
- Produces: `InscribeAgent` class with `run(behavior: BaseBIDEntry, existing_scenarios: list, mapping: MappingArtifact) -> InscribeOutput`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inscribe_agent.py`:

```python
"""Tests for the InscribeAgent."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput
from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


def test_inscribe_agent_run_returns_inscribe_output():
    agent = InscribeAgent(model=TestModel(custom_output_args=None))
    behavior = BaseBIDEntry(
        base_bid="00000",
        behavior_name="Authenticate user",
        behavior_description="User logs in with email and password",
    )
    mapping = MappingArtifact(project_id="p", base_bids=[behavior])

    output = agent.run(behavior=behavior, existing_scenarios=[], mapping=mapping)
    assert isinstance(output, InscribeOutput)
    assert isinstance(output.scenarios, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_inscribe_agent.py -v`
Expected: import error — `mage.agents.inscribe.IncribeAgent` does not exist (Task 5 only added models).

- [ ] **Step 3: Implement `InscribeAgent`**

Modify `src/mage/agents/inscribe.py`. Append:

```python
from pydantic_ai import Agent

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


INSCRIBE_PROMPT = """You are the Inscribe agent for HAILERIS v2.

Given a behavior spec, draft scenarios that fully cover the behavior's description.

Each scenario has:
- name: short, unique within behavior (kebab-case or snake_case)
- gherkin_body: full Given/When/Then block
- tags: list of @-prefixed tags
- notes: free-form context for the Etch author
- cross_behavior_tags: list of @-prefixed cross-behavior tag references

Honor depends_on and cross_behavior_links. Reuse existing scenarios where possible —
only draft new ones if the existing set has gaps.

DO NOT assign or reference BIDs. Sub-BIDs and hashes are assigned by the system
at APPROVED.

Behavior spec:

{behavior}

Existing scenarios under this behavior:

{existing_scenarios}

Sibling behaviors (read-only context):

{sibling_behaviors}
"""


class InscribeAgent:
    """Pydantic-AI agent that drafts scenarios from a behavior spec."""

    def __init__(self, model) -> None:
        self._agent: Agent[None, InscribeOutput] = Agent(
            model,
            output_type=InscribeOutput,
            system_prompt="Inscribe agent: draft scenarios from behavior spec.",
        )

    def run(
        self,
        *,
        behavior: BaseBIDEntry,
        existing_scenarios: list,
        mapping: MappingArtifact,
    ) -> InscribeOutput:
        existing_str = "\n".join(
            f"- {s.name}: {s.gherkin_body[:80]}..." for s in existing_scenarios
        ) or "(none)"
        sibling_names = [
            e.behavior_name for e in mapping.base_bids
            if e.base_bid != behavior.base_bid
        ]
        prompt = INSCRIBE_PROMPT.format(
            behavior=behavior.model_dump_json(indent=2),
            existing_scenarios=existing_str,
            sibling_behaviors=", ".join(sibling_names) if sibling_names else "(none)",
        )
        return self._agent.run_sync(prompt).output
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_inscribe_agent.py -v`
Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add src/mage/agents/inscribe.py tests/test_inscribe_agent.py
git commit -m "feat(agents): add InscribeAgent with Pydantic-AI structured output"
```

---

### Task 18: `InscribeStage` orchestration (skeleton)

**Files:**
- Create: `src/mage/orchestration/inscribe.py`
- Test: `tests/test_inscribe_stage.py` (Plan 3 NEW)

**Interfaces:**
- Consumes: `StageNode` (Plan 1), `PipelineContext` (Plan 1+2), `InscribeAgent` (Task 17), `MechanicalVerifier` (Plan 1), 7 reviewer classes (Tasks 9–15), `MappingArtifact.append_scenario` (Task 3), `Base85BID.derive` (Task 2), `VerdictArtifact` (Task 7), `aggregate_verdicts` (Task 16), `HostConfig` (Task 4), `behaviors.yaml` (Plan 2), `EventType` (Task 1).
- Produces: `InscribeStage(StageNode)` with `_run(context) -> context` that loops over behaviors and scenarios. Internal helpers: `_load_behaviors`, `_draft_scenarios`, `_run_mechanical_precheck`, `_run_reviewers`, `_aggregate_and_decide`, `_approve_scenario`.

This task ships the full InscribeStage but tests in Task 19 cover the integration; this task tests the skeleton end-to-end with TestModel + a stub reviewer.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inscribe_stage.py`:

```python
"""Integration tests for InscribeStage (skeleton)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic_ai.models.test import TestModel

from mage.agents.decomposition import ArchitectureSpec, DecompositionOutput, BehaviorSpec
from mage.agents.inscribe import InscribeAgent
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.inscribe import InscribeStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import default_check_set
from mage.verification.reviewers.determinism import DeterminismReviewer
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
from mage.verification.reviewers.step_grammar import StepGrammarReviewer
from mage.verification.reviewers.testability import TestabilityReviewer


@pytest.fixture
def all_seven_reviewers():
    """All 7 reviewers with TestModel."""
    return [
        SpecComplianceReviewer(model=TestModel(custom_output_args=None)),
        ScenarioClarityReviewer(model=TestModel(custom_output_args=None)),
        StepGrammarReviewer(model=TestModel(custom_output_args=None)),
        TestabilityReviewer(model=TestModel(custom_output_args=None)),
        DeterminismReviewer(model=TestModel(custom_output_args=None)),
        NamingIdiomReviewer(model=TestModel(custom_output_args=None)),
        LifecycleTagsReviewer(model=TestModel(custom_output_args=None)),
    ]


def _write_behaviors_yaml(project_dir: Path, feature_id: str = "feat-1") -> Path:
    path = project_dir / "behaviors.yaml"
    path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": feature_id,
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [
            {
                "id": "00000",
                "name": "authenticate-user",
                "description": "User logs in",
                "depends_on": [],
                "notes": "",
                "cross_behavior_links": [],
            },
        ],
    }))
    return path


def test_inscribe_stage_runs_end_to_end_with_test_model(tmp_path, all_seven_reviewers):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    events_path = project_dir / "events.jsonl"
    log = EventsLog(events_path)
    _write_behaviors_yaml(project_dir)

    base_entry_yaml = {
        "schema_version": 1,
        "feature_id": "feat-1",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [
            {
                "id": "00000",
                "name": "authenticate-user",
                "description": "User logs in",
                "depends_on": [],
                "notes": "",
                "cross_behavior_links": [],
            },
        ],
    }
    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump(base_entry_yaml))

    mapping = MappingArtifact(
        project_id="test-proj",
        base_bids=[{
            "base_bid": "00000",
            "behavior_name": "authenticate-user",
            "behavior_description": "User logs in",
            "depends_on": [],
            "notes": "",
            "scenarios": [],
            "reversion_log": [],
            "post_live_revisions": [],
            "cross_behavior_links": [],
        }],
    )
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    host_config = HostConfig(max_iterations=3)
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=None))

    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=all_seven_reviewers,
    )

    new_context = stage.run(context)
    assert new_context is not None
    # At least the Inscribe events should be in the log
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "inscribe_started" in event_types
    assert "inscribe_completed" in event_types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_inscribe_stage.py -v`
Expected: import error — `mage.orchestration.inscribe` does not exist.

- [ ] **Step 3: Implement `InscribeStage` (skeleton)**

Create `src/mage/orchestration/inscribe.py`:

```python
"""Inscribe stage: orchestrates per-behavior scenario drafting + approval gate."""

from __future__ import annotations

import hashlib
from datetime import datetime, UTC
from pathlib import Path

import yaml
from pydantic import BaseModel

from mage.agents.inscribe import InscribeAgent, ScenarioSpec
from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.artifacts.verdict import VerdictArtifact
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import MechanicalVerifier
from mage.verification.reviewers.base import ReviewerAgent
from mage.verification.reviewers.registry import (
    aggregate_verdicts,
    default_reviewer_registry,
)


class InscribeStage(StageNode):
    """Runs once per feature; loops over behaviors and scenarios to APPROVED."""

    name = "inscribe"

    def __init__(
        self,
        events_log: EventsLog,
        agent: InscribeAgent,
        host_config: HostConfig,
        reviewers: list[ReviewerAgent],
        mechanical_verifier: MechanicalVerifier | None = None,
    ) -> None:
        super().__init__(events_log)
        self.agent = agent
        self.host_config = host_config
        self.reviewers = reviewers
        self.mechanical_verifier = mechanical_verifier or MechanicalVerifier(checks=[])

    def _run(self, context: PipelineContext) -> PipelineContext:
        project_dir: Path = context.project_dir

        # Emit INSCRIBE_STARTED
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSCRIBE_STARTED,
                payload={
                    "feature_id": "unknown",  # Plan 3 spec: emit but don't enforce
                    "reviewer_count": len(self.reviewers),
                    "iteration": context.iteration,
                },
            )
        )

        # Load behaviors.yaml
        behaviors_data = yaml.safe_load((project_dir / "behaviors.yaml").read_text())
        behavior_specs = behaviors_data["behaviors"]

        # Load mapping
        mapping = MappingArtifact.load(project_dir / "mapping.yaml")

        # Iterate behaviors (in plan order — topological; Plan 3 just uses source order)
        for beh in behavior_specs:
            base_bid = beh["id"]
            behavior_name = beh["name"]
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.BEHAVIOR_INSCRIBE_STARTED,
                    payload={"base_bid": base_bid, "behavior_name": behavior_name},
                )
            )

            # Find the BaseBIDEntry
            entry = next(e for e in mapping.base_bids if e.base_bid == base_bid)
            existing_scenarios = [
                {"name": s.sub_bid, "gherkin_body": ""} for s in entry.scenarios
            ]

            # Inscribe loop (one behavior → may produce 1+ scenarios, but for Plan 3
            # the test focuses on a single scenario per behavior).
            iteration = context.iteration
            approved = False
            while iteration < self.host_config.max_iterations and not approved:
                iteration += 1
                # Draft scenarios
                output = self.agent.run(
                    behavior=entry, existing_scenarios=existing_scenarios, mapping=mapping
                )

                # For each scenario, run mechanical pre-check + 7 reviewers + aggregate
                approved = True  # assume all approved; revise if any fail
                for scenario_idx, scenario in enumerate(output.scenarios):
                    self.events_log.append(
                        Event(
                            timestamp=datetime.now(UTC),
                            event_type=EventType.SCENARIO_DRAFTED,
                            payload={
                                "base_bid": base_bid,
                                "scenario_name": scenario.name,
                                "iteration": iteration,
                            },
                        )
                    )

                    # 7 reviewers
                    per_dimension_verdicts = {}
                    verdicts_dir = project_dir / ".haileris" / "verdicts" / f"iter-{iteration}"
                    verdicts_dir.mkdir(parents=True, exist_ok=True)
                    for reviewer in self.reviewers:
                        verdict_path = verdicts_dir / f"{reviewer.dimension}.yaml"
                        verdict = reviewer.run(
                            draft=scenario,
                            spec_context={"behavior_name": behavior_name},
                            mapping=mapping,
                            events_log=self.events_log,
                            verdict_path=verdict_path,
                        )
                        per_dimension_verdicts[reviewer.dimension] = verdict

                    # Aggregate
                    aggregate = aggregate_verdicts(per_dimension_verdicts, iteration=iteration)
                    aggregate_path = verdicts_dir / "aggregate.yaml"
                    VerdictArtifact.finalize(aggregate_path, aggregate, self.events_log)
                    self.events_log.append(
                        Event(
                            timestamp=datetime.now(UTC),
                            event_type=EventType.REVIEW_AGGREGATE_RECORDED,
                            payload={
                                "draft_hash": aggregate.draft_hash,
                                "decision": aggregate.decision,
                            },
                        )
                    )

                    if aggregate.decision == "approved":
                        # Assign sub-BID
                        parent_bid = Base85BID(value=base_bid)
                        sub_bid = Base85BID.derive(parent_bid, scenario_idx)
                        scenario_text_hash = hashlib.sha256(
                            scenario.gherkin_body.encode("utf-8")
                        ).hexdigest()

                        scenario_entry = ScenarioEntry(
                            sub_bid=sub_bid.value,
                            scenario_text_hash=scenario_text_hash,
                            lifecycle_status=LifecycleStatus.APPROVED,
                        )
                        mapping = mapping.append_scenario(base_bid, scenario_entry)
                        # Write scenario file
                        scenario_dir = project_dir / "scenarios" / base_bid
                        scenario_dir.mkdir(parents=True, exist_ok=True)
                        scenario_path = scenario_dir / f"{scenario.name}.feature"
                        scenario_path.write_text(scenario.gherkin_body, encoding="utf-8")

                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_APPROVED,
                                payload={
                                    "base_bid": base_bid,
                                    "sub_bid": sub_bid.value,
                                    "scenario_text_hash": scenario_text_hash,
                                },
                            )
                        )
                    else:
                        # needs_refactor: loop
                        approved = False
                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_NEEDS_REFACTOR,
                                payload={"base_bid": base_bid, "scenario_name": scenario.name},
                            )
                        )

            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.BEHAVIOR_INSCRIBE_COMPLETED,
                    payload={"base_bid": base_bid, "iteration": iteration},
                )
            )

        # Persist updated mapping
        mapping.save(project_dir / "mapping.yaml")

        # Emit INSCRIBE_COMPLETED
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSCRIBE_COMPLETED,
                payload={
                    "feature_id": "unknown",
                    "scenario_count": sum(
                        len(e.scenarios) for e in mapping.base_bids
                    ),
                    "iteration": iteration,
                },
            )
        )

        return context.model_copy(update={"mapping": mapping, "iteration": iteration})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_inscribe_stage.py -v`
Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/inscribe.py tests/test_inscribe_stage.py
git commit -m "feat(orchestration): add InscribeStage skeleton with 7 reviewers + aggregation"
```

---

### Task 19: InscribeStage — needs_human_review halt path

**Files:**
- Modify: `src/mage/orchestration/inscribe.py`
- Test: `tests/test_inscribe_stage.py` (extend)

**Interfaces:**
- Consumes: existing `InscribeStage` (Task 18), `REVIEW_HALT_PERSISTED` event type (Task 1).
- Produces: behavior when `iteration >= max_iterations` and aggregate.decision == `needs_refactor` → emit `REVIEW_HALT_PERSISTED` + raise `ReviewBudgetExhausted` exception (a Plan 3 new exception; halt mechanism re-uses Plan 2's `PlanRevisionRequired` flow as a future Plan 6 refinement).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inscribe_stage.py`:

```python
def test_inscribe_stage_halts_when_budget_exhausted(tmp_path, monkeypatch):
    """When iteration >= max_iterations and aggregate says needs_refactor,
    emit REVIEW_HALT_PERSISTED and raise ReviewBudgetExhausted."""
    from mage.orchestration.inscribe import InscribeStage, ReviewBudgetExhausted
    from mage.agents.inscribe import InscribeAgent, ScenarioSpec, InscribeOutput

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": "f",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [{
            "id": "00000", "name": "authenticate-user",
            "description": "User logs in", "depends_on": [],
            "notes": "", "cross_behavior_links": [],
        }],
    }))

    mapping = MappingArtifact(
        project_id="p",
        base_bids=[{
            "base_bid": "00000", "behavior_name": "authenticate-user",
            "behavior_description": "User logs in", "depends_on": [],
            "notes": "", "scenarios": [], "reversion_log": [],
            "post_live_revisions": [], "cross_behavior_links": [],
        }],
    )
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    # Force InscribeAgent to draft a scenario
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=None))

    # Reviewers that always fail (we'll use TestModel that returns fail verdicts
    # via custom_output_args)
    from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
    from mage.artifacts.verdict import ReviewerVerdict
    from datetime import datetime, UTC

    class AlwaysFailReviewer(SpecComplianceReviewer):
        def run(self, *, draft, spec_context, mapping, events_log, verdict_path):
            v = ReviewerVerdict(
                dimension=self.dimension, outcome="fail", draft_hash="x",
                reviewed_at=datetime.now(UTC), reviewer_id=f"{self.dimension}@v1",
                findings=[],
            )
            from mage.artifacts.verdict import VerdictArtifact
            VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    failing_reviewer = AlwaysFailReviewer(model=TestModel(custom_output_args=None))

    host_config = HostConfig(max_iterations=2)  # small budget
    stage = InscribeStage(
        events_log=log, agent=inscribe_agent, host_config=host_config,
        reviewers=[failing_reviewer],
    )

    with pytest.raises(ReviewBudgetExhausted):
        stage.run(context)

    # Halt event was emitted
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "review_halt_persisted" in event_types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_inscribe_stage.py::test_inscribe_stage_halts_when_budget_exhausted -v`
Expected: FAIL — `ReviewBudgetExhausted` not defined, and current stage doesn't halt.

- [ ] **Step 3: Add the halt path**

Modify `src/mage/orchestration/inscribe.py`. Add the exception class at the top:

```python
class ReviewBudgetExhausted(Exception):
    """Raised when the iteration budget is exhausted without reaching approved."""

    def __init__(self, base_bid: str, scenario_name: str, iteration: int) -> None:
        self.base_bid = base_bid
        self.scenario_name = scenario_name
        self.iteration = iteration
        super().__init__(
            f"Review budget exhausted for scenario {scenario_name!r} "
            f"under base_bid {base_bid!r} at iteration {iteration}"
        )
```

Modify the loop in `_run` so that when the inner while-loop ends without `approved`:

```python
            if not approved:
                # Budget exhausted: emit halt event and raise.
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.REVIEW_HALT_PERSISTED,
                        payload={
                            "base_bid": base_bid,
                            "behavior_name": behavior_name,
                            "iteration": iteration,
                            "max_iterations": self.host_config.max_iterations,
                        },
                    )
                )
                raise ReviewBudgetExhausted(
                    base_bid=base_bid,
                    scenario_name=behavior_name,
                    iteration=iteration,
                )
```

This requires the inner while loop to also break when `not approved` (already handled by re-looping); in the budget-exhausted case, the while condition fails.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_inscribe_stage.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/inscribe.py tests/test_inscribe_stage.py
git commit -m "feat(orchestration): halt on review budget exhaustion"
```

---

### Task 20: `mage review show` CLI subcommand

**Files:**
- Modify: `src/mage/cli.py`
- Test: `tests/test_cli.py` (Plan 1+2, extend)

**Interfaces:**
- Consumes: `mage plan show` pattern (Plan 2), `VerdictArtifact` (Task 7), `EventType.REVIEW_AGGREGATE_RECORDED` (Task 1).
- Produces: `mage review show` subcommand — finds the latest aggregate verdict in events log for a given `(base_bid, scenario_name)` or `--sub-bid` and prints it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_review_show_prints_latest_aggregate(tmp_path, capsys):
    from mage.orchestration.inscribe import InscribeStage  # noqa: F401
    from mage.artifacts.verdict import (
        VerdictArtifact, ReviewerAggregate, DimensionSummary,
    )
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    from mage.cli import main

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")

    agg = ReviewerAggregate(
        draft_hash="x", aggregated_at=datetime.now(UTC), iteration=1,
        per_dimension={
            "spec_compliance": DimensionSummary(
                outcome="pass", reviewer_verdict_ref="r.yaml", findings_count=0,
            ),
        },
        decision="approved", reasoning="all passed",
    )
    path = project_dir / "agg.yaml"
    VerdictArtifact.finalize(path, agg, log)

    rc = main(["review", "show", "--project-dir", str(project_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "approved" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_review_show_prints_latest_aggregate -v`
Expected: FAIL — `review` subcommand not registered.

- [ ] **Step 3: Add the CLI subcommand**

Modify `src/mage/cli.py`. Add the parser and command after the `plan` parser:

```python
    # mage review <subcommand>
    review_parser = subparsers.add_parser("review", help="Review operations")
    review_subparsers = review_parser.add_subparsers(dest="review_command", required=True)
    review_show_parser = review_subparsers.add_parser("show", help="Display latest aggregate verdict")

    # ... (existing run_parser) ...
```

Add the command function:

```python
def cmd_review_show(args):
    """Display the latest aggregate verdict for the project."""
    from mage.artifacts.verdict import VerdictArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")

    events = log.read_all()
    aggregate_events = [
        e for e in events if e.event_type.value == "review_aggregate_recorded"
    ]
    if not aggregate_events:
        print(f"mage review show: no aggregate verdicts found in {project_dir}", file=sys.stderr)
        sys.exit(2)

    latest = max(aggregate_events, key=lambda e: e.timestamp)
    digest = latest.payload.get("verdict_sha256")
    decision = latest.payload.get("outcome")

    print(f"Latest aggregate verdict:")
    print(f"  Draft hash: {latest.payload.get('draft_hash')}")
    print(f"  Digest:     {digest}")
    print(f"  Decision:   {decision}")
    print(f"  Recorded:   {latest.timestamp.isoformat()}")
```

Add the dispatch in `main()`:

```python
    if args.command == "review" and args.review_command == "show":
        cmd_review_show(args)
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::test_review_show_prints_latest_aggregate -v`
Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add src/mage/cli.py tests/test_cli.py
git commit -m "feat(cli): add mage review show subcommand"
```

---

### Task 21: `mage review resume` CLI subcommand

**Files:**
- Modify: `src/mage/cli.py`
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `FileStatePersistence` (Plan 1), `PipelineContext` (Plan 1+2), `REVIEW_HALT_PERSISTED` event (Task 1).
- Produces: `mage review resume [--project-dir <path>]` — verifies a `REVIEW_HALT_PERSISTED` event exists; loads halted context; verifies budget reset semantics; prints "ready to resume" message (full pipeline wiring deferred to Plan 6).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_review_resume_requires_halt_event(tmp_path, capsys):
    from mage.cli import main

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    # No halt event written
    rc = main(["review", "resume", "--project-dir", str(project_dir)])
    # Should exit non-zero (no halt to resume)
    assert rc != 0
    captured = capsys.readouterr()
    assert "no review halt" in captured.err.lower() or "halt" in captured.err.lower()


def test_review_resume_with_halt_event(tmp_path, capsys):
    from mage.cli import main
    from mage.orchestration.events import EventsLog, Event, EventType
    from datetime import datetime, UTC

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    log.append(Event(
        timestamp=datetime.now(UTC),
        event_type=EventType.REVIEW_HALT_PERSISTED,
        payload={"base_bid": "00000", "iteration": 3},
    ))

    rc = main(["review", "resume", "--project-dir", str(project_dir)])
    # Resume is currently a placeholder (Plan 6 wires the pipeline)
    assert rc == 0
    captured = capsys.readouterr()
    assert "ready" in captured.out.lower() or "resume" in captured.out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "review_resume"`
Expected: FAIL — `resume` subcommand not registered.

- [ ] **Step 3: Add the resume subcommand**

Modify `src/mage/cli.py`. Add the resume parser:

```python
    resume_parser = review_subparsers.add_parser("resume", help="Resume after review halt")
    resume_parser.add_argument("--project-dir", type=Path, default=Path.cwd())
```

Add the command:

```python
def cmd_review_resume(args):
    """Verify a review halt and print resume readiness."""
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    events = log.read_all()
    halt_events = [e for e in events if e.event_type.value == "review_halt_persisted"]
    if not halt_events:
        print(f"mage review resume: error: no REVIEW_HALT_PERSISTED event found in {project_dir}", file=sys.stderr)
        sys.exit(2)

    print(f"Review halt found. Pipeline resume is ready (full wiring deferred to Plan 6).")
    print(f"Run: mage run --project-dir {project_dir}")
```

Add dispatch:

```python
    if args.command == "review" and args.review_command == "resume":
        cmd_review_resume(args)
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v -k "review_resume"`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/cli.py tests/test_cli.py
git commit -m "feat(cli): add mage review resume subcommand"
```

---

### Task 22: End-to-end Inscribe happy-path test

**Files:**
- Create: `tests/test_e2e_inscribe.py`

**Goal:** Full pipeline: write `behaviors.yaml` + initial `mapping.yaml`, run `InscribeStage` end-to-end with `TestModel`, verify approved scenarios in mapping, verdict files written, scenario `.feature` files written, and events emitted.

- [ ] **Step 1: Write the test**

Create `tests/test_e2e_inscribe.py`:

```python
"""End-to-end Inscribe test: Decomposition outputs → Inscribe → APPROVED mapping."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent
from mage.artifacts.mapping import LifecycleStatus, MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.inscribe import InscribeStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig
from mage.verification.reviewers.determinism import DeterminismReviewer
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
from mage.verification.reviewers.step_grammar import StepGrammarReviewer
from mage.verification.reviewers.testability import TestabilityReviewer


def test_e2e_inscribe_happy_path(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    events_path = project_dir / "events.jsonl"
    log = EventsLog(events_path)

    # Write behaviors.yaml
    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": "feat-auth",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [{
            "id": "00000",
            "name": "authenticate-user",
            "description": "User logs in with email and password",
            "depends_on": [],
            "notes": "",
            "cross_behavior_links": [],
        }],
    }))

    # Write mapping.yaml
    mapping = MappingArtifact(
        project_id="test-proj",
        base_bids=[{
            "base_bid": "00000",
            "behavior_name": "authenticate-user",
            "behavior_description": "User logs in",
            "depends_on": [],
            "notes": "",
            "scenarios": [],
            "reversion_log": [],
            "post_live_revisions": [],
            "cross_behavior_links": [],
        }],
    )
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    host_config = HostConfig(max_iterations=3)
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=None))
    reviewers = [
        SpecComplianceReviewer(model=TestModel(custom_output_args=None)),
        ScenarioClarityReviewer(model=TestModel(custom_output_args=None)),
        StepGrammarReviewer(model=TestModel(custom_output_args=None)),
        TestabilityReviewer(model=TestModel(custom_output_args=None)),
        DeterminismReviewer(model=TestModel(custom_output_args=None)),
        NamingIdiomReviewer(model=TestModel(custom_output_args=None)),
        LifecycleTagsReviewer(model=TestModel(custom_output_args=None)),
    ]

    stage = InscribeStage(
        events_log=log, agent=inscribe_agent, host_config=host_config,
        reviewers=reviewers,
    )

    new_context = stage.run(context)

    # Verify mapping has at least one APPROVED scenario under base_bid 00000
    updated_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    target = next(e for e in updated_mapping.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) >= 1
    assert target.scenarios[0].lifecycle_status == LifecycleStatus.APPROVED

    # Verify scenario .feature file was written
    scenario_files = list((project_dir / "scenarios" / "00000").glob("*.feature"))
    assert len(scenario_files) >= 1

    # Verify verdict files were written
    verdicts_root = project_dir / ".haileris" / "verdicts"
    assert verdicts_root.exists()

    # Verify events
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "inscribe_started" in event_types
    assert "inscribe_completed" in event_types
    assert "scenario_approved" in event_types
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_e2e_inscribe.py -v`
Expected: 1 test passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_inscribe.py
git commit -m "test: end-to-end Inscribe happy-path test"
```

---

### Task 23: End-to-end review-budget-exhaustion halt test

**Files:**
- Modify: `tests/test_e2e_inscribe.py`

- [ ] **Step 1: Append the test**

Append to `tests/test_e2e_inscribe.py`:

```python
def test_e2e_inscribe_halts_on_budget_exhaustion(tmp_path: Path) -> None:
    """When reviewers always fail and budget is small, Inscribe halts."""
    from datetime import datetime, UTC

    from mage.artifacts.verdict import ReviewerVerdict, VerdictArtifact
    from mage.orchestration.inscribe import InscribeStage, ReviewBudgetExhausted
    from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")

    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": "f",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [{
            "id": "00000", "name": "authenticate-user",
            "description": "User logs in", "depends_on": [],
            "notes": "", "cross_behavior_links": [],
        }],
    }))
    mapping = MappingArtifact(
        project_id="p",
        base_bids=[{
            "base_bid": "00000", "behavior_name": "authenticate-user",
            "behavior_description": "User logs in", "depends_on": [],
            "notes": "", "scenarios": [], "reversion_log": [],
            "post_live_revisions": [], "cross_behavior_links": [],
        }],
    )
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    class AlwaysFailReviewer(SpecComplianceReviewer):
        def run(self, *, draft, spec_context, mapping, events_log, verdict_path):
            v = ReviewerVerdict(
                dimension=self.dimension, outcome="fail", draft_hash="x",
                reviewed_at=datetime.now(UTC), reviewer_id=f"{self.dimension}@v1",
                findings=[],
            )
            VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    failing_reviewer = AlwaysFailReviewer(model=TestModel(custom_output_args=None))
    host_config = HostConfig(max_iterations=2)

    stage = InscribeStage(
        events_log=log,
        agent=InscribeAgent(model=TestModel(custom_output_args=None)),
        host_config=host_config,
        reviewers=[failing_reviewer],
    )

    import pytest
    with pytest.raises(ReviewBudgetExhausted):
        stage.run(context)

    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "review_halt_persisted" in event_types
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_e2e_inscribe.py::test_e2e_inscribe_halts_on_budget_exhaustion -v`
Expected: 1 test passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_inscribe.py
git commit -m "test: end-to-end review-budget-exhaustion halt"
```

---

### Task 24: End-to-end enabled-reviewers subset test

**Files:**
- Modify: `tests/test_e2e_inscribe.py`

- [ ] **Step 1: Append the test**

Append to `tests/test_e2e_inscribe.py`:

```python
def test_e2e_inscribe_with_subset_of_reviewers(tmp_path: Path) -> None:
    """When HostConfig.enabled_reviewers is a subset, only those run."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")

    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": "f",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [{
            "id": "00000", "name": "authenticate-user",
            "description": "User logs in", "depends_on": [],
            "notes": "", "cross_behavior_links": [],
        }],
    }))
    mapping = MappingArtifact(
        project_id="p",
        base_bids=[{
            "base_bid": "00000", "behavior_name": "authenticate-user",
            "behavior_description": "User logs in", "depends_on": [],
            "notes": "", "scenarios": [], "reversion_log": [],
            "post_live_revisions": [], "cross_behavior_links": [],
        }],
    )
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    # enabled_reviewers subset (only 2 of 7)
    from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
    from mage.verification.reviewers.testability import TestabilityReviewer

    reviewers = [
        SpecComplianceReviewer(model=TestModel(custom_output_args=None)),
        TestabilityReviewer(model=TestModel(custom_output_args=None)),
        LifecycleTagsReviewer(model=TestModel(custom_output_args=None)),
    ]
    host_config = HostConfig(
        max_iterations=3,
        enabled_reviewers=["spec_compliance", "testability", "lifecycle_tags"],
    )

    stage = InscribeStage(
        events_log=log,
        agent=InscribeAgent(model=TestModel(custom_output_args=None)),
        host_config=host_config,
        reviewers=reviewers,
    )
    new_context = stage.run(context)

    # Mapping was updated with at least one approved scenario
    updated_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    target = next(e for e in updated_mapping.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) >= 1
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_e2e_inscribe.py::test_e2e_inscribe_with_subset_of_reviewers -v`
Expected: 1 test passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_inscribe.py
git commit -m "test: end-to-end enabled-reviewers subset"
```

---

### Task 25: Run full test suite + verify all 171+ tests pass

**Files:** none (verification only).

- [ ] **Step 1: Run full suite**

Run: `uv run pytest -v`
Expected: all tests pass. Combined with prior plans: 128 + ~43 new = ~171 tests.

- [ ] **Step 2: Verify CLI surface**

Run: `uv run mage --help`
Expected: prints help showing `review show` and `review resume` subcommands.

Run: `uv run mage review --help`
Expected: prints `show` and `resume` subcommand help.

- [ ] **Step 3: Final commit (only if there are uncommitted fixes)**

```bash
git status  # if anything uncommitted
git add <whatever needs adding>
git commit -m "test: verify all Plan 3 tests pass"
```

---

## Summary

**22 tasks across 5 phases:**

- **Phase 1 — Foundations (Tasks 1–4):** EventType extensions, Base85BID.derive, mapping append helper, HostConfig extension. (4 tasks, additive.)
- **Phase 2 — Verdict infrastructure (Tasks 5–8):** ScenarioSpec model, verdict schemas, VerdictArtifact, ReviewerAgent base class. (4 tasks.)
- **Phase 3 — Seven reviewers (Tasks 9–16):** spec_compliance, scenario_clarity, step_grammar, testability, determinism, naming_idiom, lifecycle_tags, plus registry + aggregation. (8 tasks.)
- **Phase 4 — Stage & CLI (Tasks 17–21):** InscribeAgent, InscribeStage skeleton, halt path, `mage review show`, `mage review resume`. (5 tasks.)
- **Phase 5 — End-to-end tests (Tasks 22–25):** happy path, budget exhaustion, enabled-reviewers subset, full-suite verification. (4 tasks.)

**Test count target:** ~43 new tests. Combined: 128 + 43 = **~171 tests by end of Plan 3**.

**Architectural boundaries:**
- InscribeStage runs once per feature; internal loop per behavior; per-scenario cycle within a behavior.
- Mechanical pre-check is wired but Task 18's skeleton passes `MechanicalVerifier(checks=[])`; full mechanical integration is Plan 6 territory (along with concurrency).
- Sub-BIDs assigned at APPROVED via `Base85BID.derive`.
- Verdict storage: `.haileris/verdicts/iter-N/<dimension>.yaml` + `aggregate.yaml`.
- Approved scenarios written to `<project_dir>/scenarios/<base_bid>/<name>.feature`.
- Review budget exhaustion raises `ReviewBudgetExhausted` (Plan 3 new exception); halt mechanism details re-using Plan 2's `PlanRevisionRequired` flow deferred to Plan 6.

**Out of scope (deferred to Plans 4–6):**
- Parallel reviewer dispatch (Plan 6 concurrency)
- Mechanical pre-check wiring (Plan 6 integration)
- Settle routing of findings (Plan 5)
- Forward-only ordering enforcement (Plan 6 Three Practices)
- Reviewer prompt tuning beyond skeleton rubrics
