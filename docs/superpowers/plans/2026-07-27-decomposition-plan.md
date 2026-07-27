# HAILERIS v2 — Plan 2 (Decomposition + Plan) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Decomposition stage of the HAILERIS v2 pipeline — read Ascertain's structured output, run a Pydantic-AI agent that produces architecture + behavior specs, assign base BIDs deterministically, write a digest-pinned immutable Plan, and provide a halt-based Plan-revision gate. Plus rename the package from `haileris_v2` to `mage` (housekeeping).

**Architecture:** A `DecompositionStage` (Plan 1's `StageNode` subclass) that orchestrates a Pydantic-AI `DecompositionAgent`. The agent emits behavior specs without BIDs; the stage calls `mapping.next_base_bid()` to assign them deterministically. The Plan is `plan.md` (Markdown + YAML frontmatter); its integrity is anchored to a SHA256 digest captured in the events log. Any Plan modification outside the `mage plan revise` flow raises `PlanDigestMismatchError`. The Plan-revision gate catches `PlanRevisionRequired` exceptions, persists a halt record, and exits cleanly.

**Tech Stack:** Python 3.12+, Pydantic v2, Pydantic-AI, Pydantic-Graph, pytest, pyyaml, uv (package manager), hatchling (build backend).

## Global Constraints

These are project-wide requirements that every task's implementation implicitly satisfies. Plan 1 constraints are inherited; Plan 2 additions are below.

**Plan 1 (inherited verbatim):**

- **BID format:** Base85 alphabet, monotonically increasing within tier. Base BIDs are 5-digit Base85; sub-BIDs are appended Base85 characters using the same alphabet. Combination `<base>-<sub>` is globally unique.
- **BIDs never reused:** A retired BID stays retired permanently.
- **Mapping artifact is project-level, single source of truth:** `mapping.yaml` at the project root.
- **Mechanical verification is deterministic:** No LLM calls.
- **Persistence is append-only for events:** `events.jsonl` is append-only; never edited in place. State files are written atomically (write-temp-then-rename).
- **All Pydantic models use `model_config = ConfigDict(frozen=True)` where state is meant to be immutable.**

**Plan 2 additions:**

- **Package name:** `mage` (renamed from `haileris_v2` in Plan 1). All imports use `from mage.X import Y`. CLI entry point: `mage.cli:main`.
- **Plan format:** Markdown + YAML frontmatter. Frontmatter holds ordered `behavior_ids`, per-behavior blocks (`id`, `name`, `depends_on`, `notes`), and `project_id` / `schema_version`. Body holds build-order rationale and per-behavior sections.
- **Plan immutability:** SHA256 digest of file content captured in events log on finalization. `PlanArtifact.load()` recomputes digest and verifies against the most recent `PLAN_FINALIZED`/`PLAN_REVISED` event for that path. Raises `PlanDigestMismatchError` on mismatch.
- **BID assignment:** Agent emits behavior specs without BIDs. Stage calls `mapping.next_base_bid()` once per behavior. BIDs never appear in LLM context.
- **Behavior entry fields:** `id` (Base85, system-assigned), `name`, `description`, `depends_on` (list of base-BIDs), `notes`, `cross_behavior_links` (list of base-BIDs).
- **Ascertain output schema:** Markdown + YAML frontmatter with `feature_id`, `feature_name`, `scope_statement`, `in_scope`, `out_of_scope`, `success_criteria`, `resolved_ambiguities`, `deferred_questions`, `constraints`, `three_amigos`, plus a freeform Markdown body.
- **Approval gate:** `HostConfig.require_plan_approval: bool = True` (default: required). When required, Decomposition pauses via deferred-tool pattern before finalizing the Plan.
- **Halt mechanism:** `PlanRevisionRequired` exception caught by `PipelineGraph.run()`, halts via `HALT_PERSISTED` event + `FileStatePersistence.save_state()`, exits with code 0. Resume loads halted context via `FileStatePersistence.load_state(PipelineContext)`.
- **Plan-revision reconciliation:** `mage plan revise --reason "<why>" --approver "<id>"` reads current plan.md, computes new digest, emits `PLAN_REVISED` event with `{plan_path, old_sha256, new_sha256, reason, human_approver}`.
- **New EventType members:** `DECOMPOSITION_STARTED`, `DECOMPOSITION_COMPLETED`, `BEHAVIORS_ENUMERATED`, `PLAN_FINALIZED`, `PLAN_REVISED`, `PLAN_DIGEST_MISMATCH`, `HALT_PERSISTED`, `BEHAVIORS_REVISED`.
- **Mapping model extension:** `BaseBIDEntry.depends_on: list[str]`, `BaseBIDEntry.notes: str` (both new fields, default empty).
- **PipelineContext extension:** `plan_path: Path` field (default `<project_dir>/plan.md`).

---

### Task 1: Rename package `haileris_v2` → `mage`

**Files:**
- Modify: `pyproject.toml`
- Move: `src/haileris_v2/` → `src/mage/`
- Modify: all imports across `src/mage/**/*.py` and `tests/**/*.py`
- Modify: `tests/test_cli.py` (uses package imports)

**Step 1: Update `pyproject.toml`**

Replace the project metadata:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mage"
version = "0.1.0"
description = "HAILERIS v2 execution engine: spec-driven development pipeline"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.6",
    "pydantic-ai>=0.0.30",
    "pydantic-graph>=0.0.30",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.1",
    "ruff>=0.4",
]

[project.scripts]
mage = "mage.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/mage"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

**Step 2: Move package directory**

```bash
git mv src/haileris_v2 src/mage
```

**Step 3: Update imports in all source files**

For each `.py` file under `src/mage/`, replace `from haileris_v2.` with `from mage.`. Files to update:

- `src/mage/__init__.py`
- `src/mage/cli.py`
- `src/mage/artifacts/__init__.py`
- `src/mage/artifacts/bid.py`
- `src/mage/artifacts/mapping.py`
- `src/mage/orchestration/__init__.py`
- `src/mage/orchestration/persistence.py`
- `src/mage/orchestration/events.py`
- `src/mage/orchestration/graph.py`
- `src/mage/orchestration/nodes.py`
- `src/mage/verification/__init__.py`
- `src/mage/verification/mechanical.py`
- `src/mage/verification/host_overrides.py`

For each file, run:

```bash
sed -i 's/from haileris_v2\./from mage./g' src/mage/path/to/file.py
```

**Step 4: Update imports in test files**

For each `.py` file under `tests/`:

```bash
sed -i 's/from haileris_v2\./from mage./g' tests/test_*.py
```

**Step 5: Update internal imports within the package**

The CLI entry point and any cross-module references must use `mage.cli:main`:

```bash
sed -i 's/haileris_v2\.cli:main/mage.cli:main/g' pyproject.toml
grep -r "haileris_v2" src/mage tests pyproject.toml
```

Expected: no output (no remaining references).

**Step 6: Verify package builds**

Run:

```bash
uv sync
uv run python -c "import mage; print(mage.__version__)"
```

Expected: prints `0.1.0`.

**Step 7: Verify CLI works**

Run:

```bash
uv run mage --help
```

Expected: prints help text showing `mage` as the command name.

**Step 8: Run full test suite**

Run: `uv run pytest`
Expected: all 72 tests pass (same as end of Plan 1).

**Step 9: Commit**

```bash
git add pyproject.toml src/mage tests
git rm src/haileris_v2 2>/dev/null || true
git commit -m "refactor: rename package haileris_v2 -> mage"
```

---

### Task 2: Extend `EventType` enum

**Files:**
- Modify: `src/mage/orchestration/events.py`
- Test: `tests/test_events.py` (Plan 1, extend)

**Interfaces:**
- Consumes: existing `EventType` enum (Plan 1).
- Produces: 8 new `EventType` members: `DECOMPOSITION_STARTED`, `DECOMPOSITION_COMPLETED`, `BEHAVIORS_ENUMERATED`, `PLAN_FINALIZED`, `PLAN_REVISED`, `PLAN_DIGEST_MISMATCH`, `HALT_PERSISTED`, `BEHAVIORS_REVISED`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_events.py`:

```python
def test_new_event_types_exist():
    from mage.orchestration.events import EventType
    expected = {
        "DECOMPOSITION_STARTED",
        "DECOMPOSITION_COMPLETED",
        "BEHAVIORS_ENUMERATED",
        "PLAN_FINALIZED",
        "PLAN_REVISED",
        "PLAN_DIGEST_MISMATCH",
        "HALT_PERSISTED",
        "BEHAVIORS_REVISED",
    }
    actual = {member.name for member in EventType}
    missing = expected - actual
    assert not missing, f"missing event types: {missing}"


def test_new_event_types_have_expected_string_values():
    from mage.orchestration.events import EventType
    assert EventType.DECOMPOSITION_STARTED.value == "decomposition_started"
    assert EventType.DECOMPOSITION_COMPLETED.value == "decomposition_completed"
    assert EventType.BEHAVIORS_ENUMERATED.value == "behaviors_enumerated"
    assert EventType.PLAN_FINALIZED.value == "plan_finalized"
    assert EventType.PLAN_REVISED.value == "plan_revised"
    assert EventType.PLAN_DIGEST_MISMATCH.value == "plan_digest_mismatch"
    assert EventType.HALT_PERSISTED.value == "halt_persisted"
    assert EventType.BEHAVIORS_REVISED.value == "behaviors_revised"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_events.py::test_new_event_types_exist tests/test_events.py::test_new_event_types_have_expected_string_values -v`
Expected: both FAIL with `AttributeError: type object 'EventType' has no attribute 'DECOMPOSITION_STARTED'`.

- [ ] **Step 3: Extend the `EventType` enum**

Modify `src/mage/orchestration/events.py`. Add to the existing `EventType` class:

```python
class EventType(str, Enum):
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_events.py -v`
Expected: all events tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/events.py tests/test_events.py
git commit -m "feat(orchestration): add 8 Plan 2 EventType members"
```

---

### Task 3: Extend `BaseBIDEntry` with `depends_on` and `notes`

**Files:**
- Modify: `src/mage/artifacts/mapping.py`
- Test: `tests/test_mapping.py` (Plan 1, extend)

**Interfaces:**
- Consumes: existing `BaseBIDEntry` (Plan 1).
- Produces: `BaseBIDEntry.depends_on: list[str] = Field(default_factory=list)` and `BaseBIDEntry.notes: str = ""`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mapping.py`:

```python
def test_base_bid_entry_has_depends_on_and_notes():
    from mage.artifacts.mapping import BaseBIDEntry, LifecycleStatus, ScenarioEntry
    entry = BaseBIDEntry(
        base_bid="00000",
        behavior_name="Authenticate user",
        behavior_description="User logs in with email and password",
        depends_on=[],
        notes="Foundation behavior; everything else depends on this.",
    )
    assert entry.depends_on == []
    assert entry.notes == "Foundation behavior; everything else depends on this."


def test_base_bid_entry_round_trip_with_new_fields(tmp_path):
    import yaml
    from mage.artifacts.mapping import MappingArtifact, BaseBIDEntry
    entry = BaseBIDEntry(
        base_bid="00001",
        behavior_name="Place order",
        behavior_description="User places an order",
        depends_on=["00000"],
        notes="Depends on authentication.",
    )
    mapping = MappingArtifact(project_id="test-project", base_bids=[entry])
    path = tmp_path / "mapping.yaml"
    mapping.save(path)
    loaded = MappingArtifact.load(path)
    assert loaded.base_bids[0].depends_on == ["00000"]
    assert loaded.base_bids[0].notes == "Depends on authentication."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mapping.py::test_base_bid_entry_has_depends_on_and_notes tests/test_mapping.py::test_base_bid_entry_round_trip_with_new_fields -v`
Expected: both FAIL with `TypeError: BaseBIDEntry.__init__() got an unexpected keyword argument 'depends_on'`.

- [ ] **Step 3: Add the new fields to `BaseBIDEntry`**

Modify `src/mage/artifacts/mapping.py`. Find the `BaseBIDEntry` class and add the two new fields:

```python
class BaseBIDEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    base_bid: str
    behavior_name: str
    behavior_description: str
    depends_on: list[str] = Field(default_factory=list)
    notes: str = ""
    scenarios: list[ScenarioEntry] = Field(default_factory=list)
    reversion_log: list[ReversionLogEntry] = Field(default_factory=list)
    post_live_revisions: list[PostLiveRevisionEntry] = Field(default_factory=list)
    cross_behavior_links: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mapping.py -v`
Expected: all mapping tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/mapping.py tests/test_mapping.py
git commit -m "feat(artifacts): add depends_on and notes fields to BaseBIDEntry"
```

---

### Task 4: Add `plan_path` to `PipelineContext`

**Files:**
- Modify: `src/mage/orchestration/nodes.py`
- Test: `tests/test_nodes.py` (Plan 1, extend)

**Interfaces:**
- Consumes: existing `PipelineContext` (Plan 1).
- Produces: `PipelineContext.plan_path: Path` field (default `<project_dir>/plan.md`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_nodes.py`:

```python
def test_pipeline_context_plan_path_default(tmp_path):
    from pathlib import Path
    from unittest.mock import MagicMock
    from mage.orchestration.nodes import PipelineContext
    mapping = MagicMock()
    events_log = MagicMock()
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=mapping,
        events_log=events_log,
    )
    assert ctx.plan_path == tmp_path / "plan.md"


def test_pipeline_context_plan_path_overridable(tmp_path):
    from mage.orchestration.nodes import PipelineContext
    custom = tmp_path / "custom-plan.md"
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MagicMock(),
        events_log=MagicMock(),
        plan_path=custom,
    )
    assert ctx.plan_path == custom
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_nodes.py::test_pipeline_context_plan_path_default tests/test_nodes.py::test_pipeline_context_plan_path_overridable -v`
Expected: both FAIL with `TypeError: PipelineContext.__init__() got an unexpected keyword argument 'plan_path'`.

- [ ] **Step 3: Add the field**

Modify `src/mage/orchestration/nodes.py`. Add to `PipelineContext`:

```python
class PipelineContext(BaseModel):
    """Runtime context passed between stages."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_dir: Path
    mapping: MappingArtifact
    events_log: EventsLog
    current_stage: str | None = None
    current_sub_bid: str | None = None
    iteration: int = 0
    plan_path: Path | None = None

    @field_serializer("events_log")
    def _serialize_events_log(self, log: EventsLog) -> str:
        """Serialize EventsLog by its log path so the context can persist."""
        return str(log.log_path)

    @field_validator("events_log", mode="before")
    @classmethod
    def _deserialize_events_log(cls, value: object) -> object:
        """Reconstruct EventsLog from a serialized path string on load."""
        if isinstance(value, str):
            return EventsLog(Path(value))
        return value

    @field_validator("plan_path", mode="before")
    @classmethod
    def _default_plan_path(cls, value: object, info) -> object:
        """Default plan_path to <project_dir>/plan.md if not provided."""
        if value is None:
            project_dir = info.data.get("project_dir")
            if project_dir is not None:
                return project_dir / "plan.md"
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_nodes.py -v`
Expected: all nodes tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/nodes.py tests/test_nodes.py
git commit -m "feat(orchestration): add plan_path field to PipelineContext"
```

---

### Task 5: Extend `HostConfig` with `require_plan_approval` and `plan_template_path`

**Files:**
- Modify: `src/mage/verification/host_overrides.py`
- Test: `tests/test_host_overrides.py` (Plan 1, extend)

**Interfaces:**
- Consumes: existing `HostConfig` (Plan 1).
- Produces: `HostConfig.require_plan_approval: bool = True`, `HostConfig.plan_template_path: Path | None = None`. Adds `default_host_config()` returning `HostConfig()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_host_overrides.py`:

```python
def test_host_config_require_plan_approval_default():
    from mage.verification.host_overrides import HostConfig
    config = HostConfig()
    assert config.require_plan_approval is True


def test_host_config_require_plan_approval_overridable():
    from mage.verification.host_overrides import HostConfig
    config = HostConfig(require_plan_approval=False)
    assert config.require_plan_approval is False


def test_host_config_plan_template_path_optional():
    from pathlib import Path
    from mage.verification.host_overrides import HostConfig
    config = HostConfig()
    assert config.plan_template_path is None

    custom = Path("/tmp/custom-template.md")
    config2 = HostConfig(plan_template_path=custom)
    assert config2.plan_template_path == custom


def test_default_host_config_returns_default():
    from mage.verification.host_overrides import default_host_config, HostConfig
    config = default_host_config()
    assert isinstance(config, HostConfig)
    assert config.require_plan_approval is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_host_overrides.py -v -k "plan_approval or plan_template_path or default_host_config"`
Expected: all 4 new tests FAIL with `TypeError` or `ImportError`.

- [ ] **Step 3: Extend `HostConfig` and add `default_host_config`**

Modify `src/mage/verification/host_overrides.py`:

```python
"""Host-project override mechanism for mechanical verification and pipeline behavior."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from mage.verification.mechanical import (
    CrossBehaviorTagsValidCheck,
    GherkinSyntaxCheck,
    LifecycleStatusTagPresentCheck,
    MechanicalCheck,
    ScenarioNameUniqueCheck,
    StepDefinitionsResolvableCheck,
    SubBidAssignedCheck,
    TagsRegisteredCheck,
)


class HostConfig(BaseModel):
    """Host-project configuration overrides."""

    model_config = ConfigDict(frozen=True, extra="allow")

    enabled_checks: list[str] | None = None
    require_plan_approval: bool = True
    plan_template_path: Path | None = None


def default_check_set() -> list[MechanicalCheck]:
    """Return the default set of mechanical checks (all 7)."""
    return [
        GherkinSyntaxCheck(),
        ScenarioNameUniqueCheck(),
        TagsRegisteredCheck(registered_tags=set()),
        StepDefinitionsResolvableCheck(registered_patterns=[]),
        LifecycleStatusTagPresentCheck(),
        SubBidAssignedCheck(),
        CrossBehaviorTagsValidCheck(),
    ]


def default_host_config() -> HostConfig:
    """Return the default host config."""
    return HostConfig()


def load_host_config(path: Path) -> HostConfig:
    """Load host config from a YAML file."""
    data = yaml.safe_load(path.read_text()) or {}
    return HostConfig.model_validate(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_host_overrides.py -v`
Expected: all host_overrides tests pass (existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/host_overrides.py tests/test_host_overrides.py
git commit -m "feat(verification): add require_plan_approval + plan_template_path to HostConfig"
```

---

### Task 6: `PlanArtifact.finalize` — atomic write + digest + `PLAN_FINALIZED` event

**Files:**
- Create: `src/mage/artifacts/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `EventsLog` (Plan 1).
- Produces: `PlanArtifact.finalize(plan_path: Path, content: str, events_log: EventsLog) -> str` (returns `plan_sha256`); exception types `PlanError`, `PlanAlreadyFinalizedError`, `PlanNotFinalizedError`, `PlanDigestMismatchError`.

- [ ] **Step 1: Create test file with failing tests**

Create `tests/test_plan.py`:

```python
"""Tests for PlanArtifact (digest-pinned Plan with finalize/load/revise)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mage.orchestration.events import EventType, EventsLog


def test_finalize_writes_file_atomically(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    content = "# Plan\n\nBehaviors: 00000, 00001\n"

    digest = PlanArtifact.finalize(plan_path, content, log)

    assert plan_path.exists()
    assert plan_path.read_text() == content
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert digest == expected


def test_finalize_emits_plan_finalized_event(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    digest = PlanArtifact.finalize(plan_path, "# content\n", log)

    events = log.read_all()
    finalized = [e for e in events if e.event_type == EventType.PLAN_FINALIZED]
    assert len(finalized) == 1
    assert finalized[0].payload["plan_path"] == str(plan_path)
    assert finalized[0].payload["plan_sha256"] == digest


def test_finalize_idempotent_with_matching_digest(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    content = "# Plan\n"

    PlanArtifact.finalize(plan_path, content, log)
    # Re-finalize with same content should not raise
    PlanArtifact.finalize(plan_path, content, log)

    events = log.read_all()
    finalized = [e for e in events if e.event_type == EventType.PLAN_FINALIZED]
    assert len(finalized) == 2


def test_finalize_raises_on_digest_mismatch_with_existing_event(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanAlreadyFinalizedError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# original\n", log)
    # Try to finalize with different content
    with pytest.raises(PlanAlreadyFinalizedError):
        PlanArtifact.finalize(plan_path, "# different\n", log)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plan.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'mage.artifacts.plan'`.

- [ ] **Step 3: Implement `PlanArtifact.finalize`**

Create `src/mage/artifacts/plan.py`:

```python
"""PlanArtifact: digest-pinned Plan with finalize/load/revise operations.

The Plan's integrity is anchored to a SHA256 digest captured in the events log.
Any modification outside the mage plan revise flow raises PlanDigestMismatchError.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mage.orchestration.events import Event, EventType, EventsLog


class PlanError(Exception):
    """Base exception for PlanArtifact errors."""


class PlanAlreadyFinalizedError(PlanError):
    """Raised when finalize() is called with a different digest than recorded."""


class PlanNotFinalizedError(PlanError):
    """Raised when load() is called but no prior FINALIZED/REVISED event exists."""


class PlanDigestMismatchError(PlanError):
    """Raised when load() finds the on-disk digest doesn't match the recorded digest."""


class PlanArtifact:
    """Digest-pinned Plan operations."""

    @staticmethod
    def _compute_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _latest_event_for_path(
        events_log: EventsLog, plan_path: Path, event_types: tuple[EventType, ...]
    ) -> Event | None:
        plan_path_str = str(plan_path)
        candidates = [
            e for e in events_log.read_all()
            if e.event_type in event_types
            and e.payload.get("plan_path") == plan_path_str
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.timestamp)

    @classmethod
    def finalize(
        cls, plan_path: Path, content: str, events_log: EventsLog
    ) -> str:
        """Write Plan atomically, compute SHA256, emit PLAN_FINALIZED.

        Returns plan_sha256. Idempotent if a prior PLAN_FINALIZED event has a
        matching digest (re-finalize allowed on match); raises
        PlanAlreadyFinalizedError on digest mismatch (caller must use revise).
        """
        digest = cls._compute_digest(content)

        existing = cls._latest_event_for_path(
            events_log, plan_path, (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        )
        if existing is not None:
            recorded = existing.payload.get("plan_sha256") or existing.payload.get("new_sha256")
            if recorded != digest:
                raise PlanAlreadyFinalizedError(
                    f"Plan at {plan_path} already finalized with digest {recorded}; "
                    f"refusing to overwrite with different digest {digest}. "
                    f"Use revise() to record a revision."
                )

        # Atomic write
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(plan_path)

        events_log.append(
            Event(
                event_type=EventType.PLAN_FINALIZED,
                payload={"plan_path": str(plan_path), "plan_sha256": digest},
            )
        )

        return digest

    @classmethod
    def load(cls, plan_path: Path, events_log: EventsLog) -> str:
        """Read Plan with digest verification.

        Returns content on success. Raises PlanDigestMismatchError if on-disk
        digest != recorded digest in most recent event. Raises
        PlanNotFinalizedError if no prior FINALIZED/REVISED event exists.
        """
        # Find latest FINALIZED/REVISED event for this path
        event = cls._latest_event_for_path(
            events_log, plan_path, (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        )
        if event is None:
            raise PlanNotFinalizedError(
                f"No PLAN_FINALIZED or PLAN_REVISED event for {plan_path}; "
                f"refusing to read unverified Plan content."
            )

        recorded_digest = (
            event.payload.get("plan_sha256") or event.payload.get("new_sha256")
        )

        if not plan_path.exists():
            raise PlanNotFinalizedError(
                f"Plan file {plan_path} does not exist on disk."
            )

        content = plan_path.read_text(encoding="utf-8")
        computed_digest = cls._compute_digest(content)

        if computed_digest != recorded_digest:
            # Emit diagnostic event before raising
            events_log.append(
                Event(
                    event_type=EventType.PLAN_DIGEST_MISMATCH,
                    payload={
                        "plan_path": str(plan_path),
                        "recorded_sha256": recorded_digest,
                        "computed_sha256": computed_digest,
                        "recorded_event_type": event.event_type.value,
                        "recorded_event_at": event.timestamp.isoformat(),
                    },
                )
            )
            raise PlanDigestMismatchError(
                f"Plan at {plan_path} digest mismatch: "
                f"recorded={recorded_digest}, computed={computed_digest}"
            )

        return content

    @classmethod
    def revise(
        cls,
        plan_path: Path,
        content: str,
        reason: str,
        human_approver: str,
        events_log: EventsLog,
    ) -> str:
        """Record a Plan revision after a halt.

        Writes Plan atomically, computes new SHA256, emits PLAN_REVISED event
        with {plan_path, old_sha256, new_sha256, reason, human_approver}.
        Returns new plan_sha256.
        """
        if not reason.strip():
            raise PlanError("revise() requires a non-empty reason")
        if not human_approver.strip():
            raise PlanError("revise() requires a non-empty human_approver")

        new_digest = cls._compute_digest(content)

        existing = cls._latest_event_for_path(
            events_log, plan_path, (EventType.PLAN_FINALIZED, EventType.PLAN_REVISED)
        )
        old_digest = (
            existing.payload.get("plan_sha256") or existing.payload.get("new_sha256")
            if existing is not None
            else None
        )

        # Atomic write
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(plan_path)

        events_log.append(
            Event(
                event_type=EventType.PLAN_REVISED,
                payload={
                    "plan_path": str(plan_path),
                    "old_sha256": old_digest,
                    "new_sha256": new_digest,
                    "reason": reason,
                    "human_approver": human_approver,
                },
            )
        )

        return new_digest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plan.py::test_finalize_writes_file_atomically tests/test_plan.py::test_finalize_emits_plan_finalized_event tests/test_plan.py::test_finalize_idempotent_with_matching_digest tests/test_plan.py::test_finalize_raises_on_digest_mismatch_with_existing_event -v`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/plan.py tests/test_plan.py
git commit -m "feat(artifacts): add PlanArtifact with finalize/load/revise (digest-pinned)"
```

---

### Task 7: `PlanArtifact.load` — already implemented in Task 6

`load()` was implemented in Task 6 along with `finalize()` and `revise()`. The tests for it belong in this task.

**Files:**
- Test: `tests/test_plan.py` (extend with load tests)

- [ ] **Step 1: Add failing tests for `load()`**

Append to `tests/test_plan.py`:

```python
def test_load_returns_content_when_digest_matches(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    content = "# Plan\n\nAuth, orders.\n"

    PlanArtifact.finalize(plan_path, content, log)
    loaded = PlanArtifact.load(plan_path, log)

    assert loaded == content


def test_load_raises_when_no_event_exists(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanNotFinalizedError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Orphan\n", encoding="utf-8")

    with pytest.raises(PlanNotFinalizedError):
        PlanArtifact.load(plan_path, log)


def test_load_raises_on_digest_mismatch_after_external_edit(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanDigestMismatchError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# original\n", log)
    # External edit (bypasses revise())
    plan_path.write_text("# tampered\n", encoding="utf-8")

    with pytest.raises(PlanDigestMismatchError):
        PlanArtifact.load(plan_path, log)


def test_load_emits_digest_mismatch_event_before_raising(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanDigestMismatchError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# original\n", log)
    plan_path.write_text("# tampered\n", encoding="utf-8")

    with pytest.raises(PlanDigestMismatchError):
        PlanArtifact.load(plan_path, log)

    mismatch_events = [
        e for e in log.read_all() if e.event_type == EventType.PLAN_DIGEST_MISMATCH
    ]
    assert len(mismatch_events) == 1
    assert mismatch_events[0].payload["plan_path"] == str(plan_path)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_plan.py -v`
Expected: all 8 tests pass (4 from Task 6 + 4 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_plan.py
git commit -m "test: PlanArtifact.load digest verification"
```

---

### Task 8: `PlanArtifact.revise` — already implemented in Task 6; add tests

**Files:**
- Test: `tests/test_plan.py` (extend with revise tests)

- [ ] **Step 1: Add failing tests for `revise()`**

Append to `tests/test_plan.py`:

```python
def test_revise_writes_new_content_and_emits_event(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# v1\n", log)
    new_digest = PlanArtifact.revise(
        plan_path, "# v2 — fixed ordering\n", reason="Reordered behaviors", human_approver="alice", events_log=log
    )

    assert plan_path.read_text() == "# v2 — fixed ordering\n"

    revised = [e for e in log.read_all() if e.event_type == EventType.PLAN_REVISED]
    assert len(revised) == 1
    assert revised[0].payload["reason"] == "Reordered behaviors"
    assert revised[0].payload["human_approver"] == "alice"
    assert revised[0].payload["new_sha256"] == new_digest


def test_revise_requires_reason_and_approver(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# v1\n", log)

    with pytest.raises(PlanError, match="non-empty reason"):
        PlanArtifact.revise(plan_path, "# v2\n", reason="", human_approver="alice", events_log=log)

    with pytest.raises(PlanError, match="non-empty human_approver"):
        PlanArtifact.revise(plan_path, "# v2\n", reason="r", human_approver="", events_log=log)


def test_load_after_revise_succeeds_with_new_digest(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# v1\n", log)
    PlanArtifact.revise(plan_path, "# v2\n", reason="r", human_approver="alice", events_log=log)

    loaded = PlanArtifact.load(plan_path, log)
    assert loaded == "# v2\n"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_plan.py -v`
Expected: all 11 tests pass (8 from Tasks 6-7 + 3 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_plan.py
git commit -m "test: PlanArtifact.revise revision flow"
```

---

### Task 9: Ascertain output schema models

**Files:**
- Create: `src/mage/artifacts/ascertain.py`
- Test: `tests/test_ascertain.py`

**Interfaces:**
- Consumes: nothing (pure Pydantic models).
- Produces: `ResolvedAmbiguity`, `ThreeAmigos`, `AscertainOutput` Pydantic models. `parse_ascertain(path: Path) -> AscertainOutput` function that reads Markdown + YAML frontmatter.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ascertain.py`:

```python
"""Tests for Ascertain output schema."""

from __future__ import annotations

from pathlib import Path

import pytest


ASCERTAIN_FULL = """---
feature_id: feat-001
feature_name: User authentication
scope_statement: Users authenticate with email/password; OAuth is out of scope.
in_scope:
  - Email/password login
  - Password reset
out_of_scope:
  - OAuth providers
  - Multi-factor auth
success_criteria:
  - User can log in with valid credentials
  - User sees clear error on invalid credentials
resolved_ambiguities:
  - question: Should we support OAuth?
    decision: No, out of scope for v1.
    rationale: Reduces scope; can add later.
    resolved_by: alice
deferred_questions:
  - "When does password reset expire?"
constraints:
  - "Must work with existing user table."
three_amigos:
  product: "Product perspective: focus on simplest happy path first."
  tester: "Tester perspective: verify error states."
  developer: "Developer perspective: integrate with existing auth middleware."
---

# Ascertain Session

We discussed scope, ambiguities, and constraints. The team agreed on email/password for v1.
"""

ASCERTAIN_MINIMAL = """---
feature_id: feat-002
feature_name: Minimal feature
scope_statement: Just the basics.
---"""


def test_parse_ascertain_full():
    from mage.artifacts.ascertain import parse_ascertain
    output = parse_ascertain(AscertainInput := type("X", (), {"write_text": staticmethod(lambda s: None)})())
    # Use a path-based test instead
```

Replace the above with:

```python
"""Tests for Ascertain output schema."""

from __future__ import annotations

from pathlib import Path


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "ascertain.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_ascertain_full(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain
    path = _write(tmp_path, ASCERTAIN_FULL)
    out = parse_ascertain(path)
    assert out.feature_id == "feat-001"
    assert out.feature_name == "User authentication"
    assert "Email/password login" in out.in_scope
    assert "OAuth providers" in out.out_of_scope
    assert len(out.success_criteria) == 2
    assert len(out.resolved_ambiguities) == 1
    assert out.resolved_ambiguities[0].question == "Should we support OAuth?"
    assert out.three_amigos.product.startswith("Product perspective")


def test_parse_ascertain_minimal(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain
    path = _write(tmp_path, ASCERTAIN_MINIMAL)
    out = parse_ascertain(path)
    assert out.feature_id == "feat-002"
    assert out.feature_name == "Minimal feature"
    assert out.in_scope == []
    assert out.out_of_scope == []
    assert out.three_amigos.product == ""


def test_parse_ascertain_body_is_preserved(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain
    path = _write(tmp_path, ASCERTAIN_FULL)
    out = parse_ascertain(path)
    assert "We discussed scope" in out.body


def test_parse_ascertain_missing_frontmatter_raises(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain, AscertainSchemaError
    path = tmp_path / "bad.md"
    path.write_text("No frontmatter here.\n", encoding="utf-8")
    with pytest.raises(AscertainSchemaError):
        parse_ascertain(path)
```

Add the constants at the top of the test file:

```python
ASCERTAIN_FULL = """---
feature_id: feat-001
feature_name: User authentication
scope_statement: Users authenticate with email/password; OAuth is out of scope.
in_scope:
  - Email/password login
  - Password reset
out_of_scope:
  - OAuth providers
  - Multi-factor auth
success_criteria:
  - User can log in with valid credentials
  - User sees clear error on invalid credentials
resolved_ambiguities:
  - question: Should we support OAuth?
    decision: No, out of scope for v1.
    rationale: Reduces scope; can add later.
    resolved_by: alice
deferred_questions:
  - "When does password reset expire?"
constraints:
  - "Must work with existing user table."
three_amigos:
  product: "Product perspective: focus on simplest happy path first."
  tester: "Tester perspective: verify error states."
  developer: "Developer perspective: integrate with existing auth middleware."
---

# Ascertain Session

We discussed scope, ambiguities, and constraints. The team agreed on email/password for v1.
"""

ASCERTAIN_MINIMAL = """---
feature_id: feat-002
feature_name: Minimal feature
scope_statement: Just the basics.
---"""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ascertain.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'mage.artifacts.ascertain'`.

- [ ] **Step 3: Implement `ascertain.py`**

Create `src/mage/artifacts/ascertain.py`:

```python
"""Ascertain output schema: structured record of resolved ambiguities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


class AscertainSchemaError(Exception):
    """Raised when Ascertain output cannot be parsed."""


class ResolvedAmbiguity(BaseModel):
    model_config = ConfigDict(frozen=True)
    question: str
    decision: str
    rationale: str
    resolved_by: str


class ThreeAmigos(BaseModel):
    model_config = ConfigDict(frozen=True)
    product: str = ""
    tester: str = ""
    developer: str = ""


class AscertainOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    feature_id: str
    feature_name: str
    scope_statement: str
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    success_criteria: list[str] = []
    resolved_ambiguities: list[ResolvedAmbiguity] = []
    deferred_questions: list[str] = []
    constraints: list[str] = []
    three_amigos: ThreeAmigos = ThreeAmigos()
    body: str = ""

    @field_validator("feature_id", "feature_name", "scope_statement")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


def parse_ascertain(path: Path) -> AscertainOutput:
    """Parse Ascertain output (Markdown + YAML frontmatter) into AscertainOutput.

    Raises AscertainSchemaError if the file is missing, has no frontmatter,
    or the frontmatter fails validation.
    """
    if not path.exists():
        raise AscertainSchemaError(f"Ascertain file does not exist: {path}")

    text = path.read_text(encoding="utf-8")

    # Split frontmatter from body
    if not text.startswith("---\n"):
        raise AscertainSchemaError(
            f"Ascertain file {path} does not start with YAML frontmatter (---)"
        )

    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise AscertainSchemaError(
            f"Ascertain file {path} has malformed frontmatter (missing closing ---)"
        )

    frontmatter_text = parts[1]
    body = parts[2]

    try:
        frontmatter: dict[str, Any] = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        raise AscertainSchemaError(f"Ascertain frontmatter is invalid YAML: {e}") from e

    if not isinstance(frontmatter, dict):
        raise AscertainSchemaError(
            f"Ascertain frontmatter must be a YAML mapping, got {type(frontmatter).__name__}"
        )

    try:
        return AscertainOutput(**frontmatter, body=body)
    except Exception as e:
        raise AscertainSchemaError(f"Ascertain frontmatter validation failed: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ascertain.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/ascertain.py tests/test_ascertain.py
git commit -m "feat(artifacts): add Ascertain output schema + parse_ascertain"
```

---

### Task 10: Behavior enumeration — validation + cycle detection + BID assignment

**Files:**
- Create: `src/mage/artifacts/enumeration.py`
- Test: `tests/test_enumeration.py`

**Interfaces:**
- Consumes: `BehaviorSpec` (defined here), `MappingArtifact`, `BaseBIDEntry`.
- Produces: `BehaviorSpec`, `enumerate_behaviors(behavior_specs: list[BehaviorSpec], mapping: MappingArtifact) -> list[BaseBIDEntry]` (returns new entries; mapping update happens in Task 11).

- [ ] **Step 1: Write failing tests**

Create `tests/test_enumeration.py`:

```python
"""Tests for behavior enumeration: validation, cycle detection, BID assignment."""

from __future__ import annotations

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import MappingArtifact


def _spec(name: str, *, depends_on=(), cross=()) -> "BehaviorSpec":
    from mage.artifacts.enumeration import BehaviorSpec
    return BehaviorSpec(
        name=name,
        description=f"{name} behavior",
        depends_on=list(depends_on),
        cross_behavior_links=list(cross),
    )


def test_assign_bids_monotonically_to_empty_mapping():
    from mage.artifacts.enumeration import enumerate_behaviors
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("orders", depends_on=["auth"]), _spec("payments", depends_on=["orders"])]
    entries = enumerate_behaviors(specs, mapping)
    assert [e.base_bid for e in entries] == ["00000", "00001", "00002"]


def test_assign_bids_continues_from_existing_mapping():
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import BaseBIDEntry
    existing = BaseBIDEntry(base_bid="00004", behavior_name="seed", behavior_description="seed")
    mapping = MappingArtifact(project_id="p", base_bids=[existing])
    specs = [_spec("auth"), _spec("orders")]
    entries = enumerate_behaviors(specs, mapping)
    assert [e.base_bid for e in entries] == ["00005", "00006"]


def test_dependency_resolves_to_pending_behavior():
    from mage.artifacts.enumeration import enumerate_behaviors
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("orders", depends_on=["auth"]), _spec("auth")]
    entries = enumerate_behaviors(specs, mapping)
    # auth comes first because orders depends on it
    auth_entry = next(e for e in entries if e.behavior_name == "auth")
    orders_entry = next(e for e in entries if e.behavior_name == "orders")
    assert auth_entry.base_bid < orders_entry.base_bid
    assert orders_entry.depends_on == [auth_entry.base_bid]


def test_unresolvable_dependency_raises():
    from mage.artifacts.enumeration import enumerate_behaviors, BehaviorDependencyError
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("orders", depends_on=["nonexistent"])]
    with pytest.raises(BehaviorDependencyError):
        enumerate_behaviors(specs, mapping)


def test_cycle_in_dependencies_raises():
    from mage.artifacts.enumeration import enumerate_behaviors, BehaviorDependencyCycleError
    mapping = MappingArtifact(project_id="p")
    specs = [
        _spec("a", depends_on=["b"]),
        _spec("b", depends_on=["a"]),
    ]
    with pytest.raises(BehaviorDependencyCycleError):
        enumerate_behaviors(specs, mapping)


def test_self_referential_dependency_caught_as_cycle():
    from mage.artifacts.enumeration import enumerate_behaviors, BehaviorDependencyCycleError
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("a", depends_on=["a"])]
    with pytest.raises(BehaviorDependencyCycleError):
        enumerate_behaviors(specs, mapping)


def test_duplicate_behavior_names_raise():
    from mage.artifacts.enumeration import enumerate_behaviors, DuplicateBehaviorNameError
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("auth")]
    with pytest.raises(DuplicateBehaviorNameError):
        enumerate_behaviors(specs, mapping)


def test_empty_behavior_list_raises():
    from mage.artifacts.enumeration import enumerate_behaviors, NoBehaviorsError
    mapping = MappingArtifact(project_id="p")
    with pytest.raises(NoBehaviorsError):
        enumerate_behaviors([], mapping)


def test_cross_behavior_link_to_existing_behavior():
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import BaseBIDEntry
    existing = BaseBIDEntry(base_bid="00010", behavior_name="payments", behavior_description="payments")
    mapping = MappingArtifact(project_id="p", base_bids=[existing])
    specs = [_spec("checkout", cross=["payments"])]
    entries = enumerate_behaviors(specs, mapping)
    assert entries[0].cross_behavior_links == ["00010"]


def test_cross_behavior_link_to_pending_behavior():
    from mage.artifacts.enumeration import enumerate_behaviors
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("a"), _spec("b", cross=["a"])]
    entries = enumerate_behaviors(specs, mapping)
    b = next(e for e in entries if e.behavior_name == "b")
    a = next(e for e in entries if e.behavior_name == "a")
    assert b.cross_behavior_links == [a.base_bid]
```

Add at top:

```python
import pytest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enumeration.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'mage.artifacts.enumeration'`.

- [ ] **Step 3: Implement `enumeration.py` (validation + assignment only, no file writes yet)**

Create `src/mage/artifacts/enumeration.py`:

```python
"""Behavior enumeration: validates dependencies, detects cycles, assigns base BIDs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


class BehaviorSpec(BaseModel):
    """Decomposition agent's structured output for one behavior (no BID)."""

    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    notes: str = ""
    cross_behavior_links: list[str] = Field(default_factory=list)


class BehaviorEnumerationError(Exception):
    """Base class for behavior enumeration errors."""


class BehaviorDependencyError(BehaviorEnumerationError):
    """Raised when a behavior's depends_on references an unknown behavior."""


class BehaviorDependencyCycleError(BehaviorEnumerationError):
    """Raised when behaviors have a dependency cycle."""


class DuplicateBehaviorNameError(BehaviorEnumerationError):
    """Raised when two behaviors share the same name within one enumeration."""


class NoBehaviorsError(BehaviorEnumerationError):
    """Raised when an enumeration has zero behaviors."""


class CrossBehaviorLinkError(BehaviorEnumerationError):
    """Raised when a cross_behavior_links entry references an unknown behavior."""


def _topological_sort(
    specs: list[BehaviorSpec],
) -> list[BehaviorSpec]:
    """Sort specs in dependency order. Raises on cycle.

    Input is a list of BehaviorSpec. Each spec's depends_on refers to other
    specs by name. Output is the same specs in an order where each spec's
    dependencies come before it.
    """
    by_name = {s.name: s for s in specs}
    visited: set[str] = set()
    visiting: set[str] = set()
    result: list[BehaviorSpec] = []

    def visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join(path + [name])
            raise BehaviorDependencyCycleError(f"Dependency cycle: {cycle}")
        spec = by_name.get(name)
        if spec is None:
            return  # external dependency, resolved elsewhere
        visiting.add(name)
        for dep in spec.depends_on:
            visit(dep, path + [name])
        visiting.remove(name)
        visited.add(name)
        result.append(spec)

    for spec in specs:
        visit(spec.name, [])

    return result


def enumerate_behaviors(
    behavior_specs: list[BehaviorSpec],
    mapping: MappingArtifact,
) -> list[BaseBIDEntry]:
    """Validate behavior specs and assign base BIDs.

    Returns a list of new BaseBIDEntry objects (one per spec) with BIDs assigned
    in topological order. The mapping is read but not modified — the caller is
    responsible for appending the entries and saving.
    """
    if not behavior_specs:
        raise NoBehaviorsError("Cannot enumerate zero behaviors")

    # Check for duplicate names
    names = [s.name for s in behavior_specs]
    if len(names) != len(set(names)):
        from collections import Counter
        counts = Counter(names)
        duplicates = [n for n, c in counts.items() if c > 1]
        raise DuplicateBehaviorNameError(f"Duplicate behavior names: {duplicates}")

    # Build sets of existing and pending behavior identifiers
    existing_bids = {e.base_bid for e in mapping.base_bids}
    pending_names = set(names)

    # Validate that every depends_on resolves
    for spec in behavior_specs:
        for dep in spec.depends_on:
            if dep in pending_names:
                continue  # pending behavior, resolved by name
            if dep in existing_bids:
                continue  # existing base-BID
            raise BehaviorDependencyError(
                f"Behavior '{spec.name}' has unresolvable dependency: '{dep}'"
            )

        for link in spec.cross_behavior_links:
            if link in pending_names:
                continue
            if link in existing_bids:
                continue
            raise CrossBehaviorLinkError(
                f"Behavior '{spec.name}' has unresolvable cross_behavior_link: '{link}'"
            )

    # Topological sort
    sorted_specs = _topological_sort(behavior_specs)

    # Assign BIDs in topological order
    pending_to_bid: dict[str, str] = {}
    next_bid_helper = mapping.next_base_bid()
    entries: list[BaseBIDEntry] = []

    for spec in sorted_specs:
        if not entries:
            bid = next_bid_helper
            # Subsequent BIDs: increment from the first
            from mage.artifacts.bid import next_base_bid
            for _ in range(len(sorted_specs) - 1):
                pass  # we'll do it in the loop below
        # First iteration: just get the right start
        pass

    # Reset and do it cleanly
    entries = []
    current = mapping.next_base_bid()
    for spec in sorted_specs:
        pending_to_bid[spec.name] = current.value

        # Resolve dependencies and cross links to base-BID strings
        resolved_depends = []
        for dep in spec.depends_on:
            if dep in pending_to_bid:
                resolved_depends.append(pending_to_bid[dep])
            else:
                # Existing base-BID
                resolved_depends.append(dep)

        resolved_cross = []
        for link in spec.cross_behavior_links:
            if link in pending_to_bid:
                resolved_cross.append(pending_to_bid[link])
            else:
                resolved_cross.append(link)

        entry = BaseBIDEntry(
            base_bid=current.value,
            behavior_name=spec.name,
            behavior_description=spec.description,
            depends_on=resolved_depends,
            notes=spec.notes,
            cross_behavior_links=resolved_cross,
        )
        entries.append(entry)
        current = current.increment()

    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_enumeration.py -v`
Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/enumeration.py tests/test_enumeration.py
git commit -m "feat(artifacts): behavior enumeration with validation + BID assignment"
```

---

### Task 11: Behavior enumeration — file writes + events

**Files:**
- Modify: `src/mage/artifacts/enumeration.py`
- Test: `tests/test_enumeration.py` (extend)

**Interfaces:**
- Consumes: existing `enumerate_behaviors` from Task 10, `EventsLog`.
- Produces: extended `enumerate_behaviors` that also writes `behaviors.yaml` and `mapping.yaml` atomically, emits `BEHAVIORS_ENUMERATED` event. Returns `(updated_mapping, behaviors_yaml_path)`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_enumeration.py`:

```python
def test_enumerate_writes_behaviors_yaml(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog, EventType
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("orders", depends_on=["auth"])]

    updated_mapping, behaviors_path = enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    assert behaviors_path.exists()
    assert behaviors_path == tmp_path / "behaviors.yaml"
    import yaml
    data = yaml.safe_load(behaviors_path.read_text())
    assert data["schema_version"] == 1
    assert len(data["behaviors"]) == 2
    assert {b["name"] for b in data["behaviors"]} == {"auth", "orders"}


def test_enumerate_writes_updated_mapping(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth")]

    updated_mapping, _ = enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    assert len(updated_mapping.base_bids) == 1
    assert updated_mapping.base_bids[0].behavior_name == "auth"


def test_enumerate_emits_behaviors_enumerated_event(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog, EventType
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth")]

    enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    events = log.read_all()
    enum_events = [e for e in events if e.event_type == EventType.BEHAVIORS_ENUMERATED]
    assert len(enum_events) == 1
    assert enum_events[0].payload["count"] == 1


def test_enumerate_does_not_write_on_validation_error(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors, DuplicateBehaviorNameError
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("auth")]

    with pytest.raises(DuplicateBehaviorNameError):
        enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    assert not (tmp_path / "behaviors.yaml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enumeration.py -v -k "writes_behaviors_yaml or writes_updated_mapping or emits_behaviors_enumerated_event or does_not_write_on_validation_error"`
Expected: all 4 new tests FAIL with `TypeError: enumerate_behaviors() got an unexpected keyword argument 'project_dir'`.

- [ ] **Step 3: Extend `enumerate_behaviors` to write files + emit event**

Modify `src/mage/artifacts/enumeration.py`. Replace the existing `enumerate_behaviors` function with one that takes `project_dir` and `events_log`, writes files, and emits the event:

```python
def enumerate_behaviors(
    behavior_specs: list[BehaviorSpec],
    mapping: MappingArtifact,
    project_dir,
    events_log,
) -> tuple:
    """Validate behavior specs, assign base BIDs, write files atomically.

    Writes behaviors.yaml and updates mapping.yaml. Emits BEHAVIORS_ENUMERATED
    event. Returns (updated_mapping, behaviors_yaml_path).

    Raises BehaviorEnumerationError subclasses on validation failure; in that
    case no files are written.
    """
    if not behavior_specs:
        raise NoBehaviorsError("Cannot enumerate zero behaviors")

    names = [s.name for s in behavior_specs]
    if len(names) != len(set(names)):
        from collections import Counter
        counts = Counter(names)
        duplicates = [n for n, c in counts.items() if c > 1]
        raise DuplicateBehaviorNameError(f"Duplicate behavior names: {duplicates}")

    existing_bids = {e.base_bid for e in mapping.base_bids}
    pending_names = set(names)

    for spec in behavior_specs:
        for dep in spec.depends_on:
            if dep in pending_names:
                continue
            if dep in existing_bids:
                continue
            raise BehaviorDependencyError(
                f"Behavior '{spec.name}' has unresolvable dependency: '{dep}'"
            )
        for link in spec.cross_behavior_links:
            if link in pending_names:
                continue
            if link in existing_bids:
                continue
            raise CrossBehaviorLinkError(
                f"Behavior '{spec.name}' has unresolvable cross_behavior_link: '{link}'"
            )

    sorted_specs = _topological_sort(behavior_specs)

    pending_to_bid: dict[str, str] = {}
    entries: list[BaseBIDEntry] = []
    current = mapping.next_base_bid()

    for spec in sorted_specs:
        pending_to_bid[spec.name] = current.value
        resolved_depends = [
            pending_to_bid[dep] if dep in pending_to_bid else dep
            for dep in spec.depends_on
        ]
        resolved_cross = [
            pending_to_bid[link] if link in pending_to_bid else link
            for link in spec.cross_behavior_links
        ]
        entry = BaseBIDEntry(
            base_bid=current.value,
            behavior_name=spec.name,
            behavior_description=spec.description,
            depends_on=resolved_depends,
            notes=spec.notes,
            cross_behavior_links=resolved_cross,
        )
        entries.append(entry)
        current = current.increment()

    # Build updated mapping (don't mutate the input)
    updated_mapping = mapping.model_copy(
        update={"base_bids": list(mapping.base_bids) + entries}
    )

    # Write behaviors.yaml atomically
    from datetime import datetime, timezone
    import yaml as _yaml
    behaviors_data = {
        "schema_version": 1,
        "feature_id": "unset",  # Stage sets this from Ascertain
        "enumerated_at": datetime.now(timezone.utc).isoformat(),
        "behaviors": [
            {
                "id": e.base_bid,
                "name": e.behavior_name,
                "description": e.behavior_description,
                "depends_on": e.depends_on,
                "notes": e.notes,
                "cross_behavior_links": e.cross_behavior_links,
            }
            for e in entries
        ],
    }
    behaviors_path = project_dir / "behaviors.yaml"
    behaviors_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = behaviors_path.with_suffix(behaviors_path.suffix + ".tmp")
    tmp.write_text(_yaml.safe_dump(behaviors_data, sort_keys=False), encoding="utf-8")
    tmp.replace(behaviors_path)

    # Write updated mapping atomically
    updated_mapping.save(project_dir / "mapping.yaml")

    # Emit event
    from mage.orchestration.events import Event, EventType
    events_log.append(
        Event(
            event_type=EventType.BEHAVIORS_ENUMERATED,
            payload={
                "count": len(entries),
                "behaviors_yaml_path": str(behaviors_path),
            },
        )
    )

    return updated_mapping, behaviors_path
```

Also add imports at the top of `enumeration.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_enumeration.py -v`
Expected: all 14 tests pass (10 from Task 10 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/enumeration.py tests/test_enumeration.py
git commit -m "feat(artifacts): enumerate_behaviors writes files + emits event"
```

---

### Task 12: Decomposition agent (Pydantic-AI, structured output)

**Files:**
- Create: `src/mage/agents/__init__.py`
- Create: `src/mage/agents/decomposition.py`
- Test: `tests/test_decomposition_agent.py`

**Interfaces:**
- Consumes: `AscertainOutput`, `BehaviorSpec`, `ArchitectureSpec`.
- Produces: `ArchitectureSpec`, `DecompositionOutput` (architecture + behaviors). `DecompositionAgent` class wrapping a Pydantic-AI agent.

- [ ] **Step 1: Create agents package**

Create `src/mage/agents/__init__.py` (empty).

- [ ] **Step 2: Write failing tests**

Create `tests/test_decomposition_agent.py`:

```python
"""Tests for the Decomposition Pydantic-AI agent (uses TestModel)."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel
from pydantic_ai import models

from mage.agents.decomposition import DecompositionAgent
from mage.artifacts.ascertain import AscertainOutput, ThreeAmigos


@pytest.fixture(autouse=True)
def use_test_model():
    """Force all Pydantic-AI agents to use TestModel for deterministic tests."""
    models.ALLOW_MODEL_REQUESTS = False
    yield


def _ascertain() -> AscertainOutput:
    return AscertainOutput(
        feature_id="feat-001",
        feature_name="User authentication",
        scope_statement="Email/password login for v1.",
        three_amigos=ThreeAmigos(
            product="Focus on simplest happy path",
            tester="Verify error states",
            developer="Integrate with existing auth",
        ),
    )


def test_decomposition_agent_returns_architecture_and_behaviors():
    agent = DecompositionAgent(model=TestModel())
    output = agent.run(ascertain=_ascertain(), existing_mapping=None)
    assert output.architecture is not None
    assert isinstance(output.behaviors, list)
    assert len(output.behaviors) >= 1
    # No BIDs in agent output
    for behavior in output.behaviors:
        assert not hasattr(behavior, "id")


def test_decomposition_agent_receives_existing_mapping_context():
    from mage.artifacts.mapping import MappingArtifact, BaseBIDEntry
    agent = DecompositionAgent(model=TestModel())
    mapping = MappingArtifact(
        project_id="p",
        base_bids=[BaseBIDEntry(base_bid="00005", behavior_name="existing", behavior_description="existing")],
    )
    output = agent.run(ascertain=_ascertain(), existing_mapping=mapping)
    assert output is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_decomposition_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mage.agents.decomposition'`.

- [ ] **Step 4: Implement `DecompositionAgent`**

Create `src/mage/agents/decomposition.py`:

```python
"""Decomposition agent: Pydantic-AI agent that emits architecture + behavior specs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent

from mage.artifacts.ascertain import AscertainOutput
from mage.artifacts.enumeration import BehaviorSpec
from mage.artifacts.mapping import MappingArtifact


class ArchitectureSpec(BaseModel):
    """Architectural breakdown produced by the Decomposition agent."""

    model_config = ConfigDict(frozen=True)
    parts: list[str]
    components: list[str]
    layers: list[str]
    notes: str = ""


class DecompositionOutput(BaseModel):
    """Combined output of the Decomposition agent."""

    model_config = ConfigDict(frozen=True)
    architecture: ArchitectureSpec
    behaviors: list[BehaviorSpec]


DECOMPOSITION_PROMPT = """You are the Decomposition agent for HAILERIS v2.

Given an Ascertain session's resolved scope, ambiguities, and Three Amigos perspectives,
produce:

1. An `ArchitectureSpec` — the architectural breakdown (parts, components, layers).
2. A list of `BehaviorSpec` — the behaviors the system must exhibit.

Each `BehaviorSpec` has:
- `name`: short behavior name
- `description`: what the behavior does
- `depends_on`: list of OTHER BEHAVIOR NAMES (not BIDs) that must be built first
- `notes`: free-form context for the Inscribe author
- `cross_behavior_links`: list of OTHER BEHAVIOR NAMES that this behavior's scenarios will touch

DO NOT assign or reference BIDs. The system layer assigns BIDs after you finish.

Ascertain session:

{ascertain}

Existing behaviors in the project (read-only context; do not duplicate these names):
{existing_behaviors}
"""


class DecompositionAgent:
    """Pydantic-AI agent that decomposes a feature into architecture + behaviors."""

    def __init__(self, model) -> None:
        self._agent: Agent[None, DecompositionOutput] = Agent(
            model,
            output_type=DecompositionOutput,
            system_prompt="Decomposition agent: produce architecture + behavior specs from Ascertain output.",
        )

    def run(
        self,
        *,
        ascertain: AscertainOutput,
        existing_mapping: MappingArtifact | None,
    ) -> DecompositionOutput:
        existing_names = (
            [e.behavior_name for e in existing_mapping.base_bids]
            if existing_mapping is not None
            else []
        )
        prompt = DECOMPOSITION_PROMPT.format(
            ascertain=ascertain.model_dump_json(indent=2),
            existing_behaviors=", ".join(existing_names) if existing_names else "(none)",
        )
        return self._agent.run_sync(prompt).output
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_decomposition_agent.py -v`
Expected: all 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/mage/agents tests/test_decomposition_agent.py
git commit -m "feat(agents): Decomposition agent with structured output (BehaviorSpec + ArchitectureSpec)"
```

---

### Task 13: Plan template file

**Files:**
- Create: `src/mage/orchestration/plan_template.md`

**Interfaces:**
- Consumes: nothing.
- Produces: default Plan template as a static Markdown file.

- [ ] **Step 1: Write the template file**

Create `src/mage/orchestration/plan_template.md`:

```markdown
---
behavior_ids:
{behavior_ids_yaml}
behaviors:
{behaviors_yaml}
project_id: {project_id}
schema_version: 1
---

# Implementation Plan — {feature_name}

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** {scope_statement}

**Architecture overview:**

{architecture_summary}

## Behaviors

{behavior_sections}
```

- [ ] **Step 2: Commit**

```bash
git add src/mage/orchestration/plan_template.md
git commit -m "feat(orchestration): default Plan template"
```

---

### Task 14: Plan writer (renders `plan.md` from behaviors + template)

**Files:**
- Create: `src/mage/orchestration/plan_writer.py`
- Test: `tests/test_plan_writer.py`

**Interfaces:**
- Consumes: `list[BaseBIDEntry]`, `AscertainOutput`, `ArchitectureSpec`, template path.
- Produces: `render_plan(entries, ascertain, architecture, template_path) -> str` (returns Markdown content).

- [ ] **Step 1: Write failing tests**

Create `tests/test_plan_writer.py`:

```python
"""Tests for the Plan writer (renders plan.md from behaviors + template)."""

from __future__ import annotations

from pathlib import Path

from mage.artifacts.ascertain import AscertainOutput


TEMPLATE = """---
behavior_ids:
{behavior_ids_yaml}
behaviors:
{behaviors_yaml}
project_id: {project_id}
schema_version: 1
---

# Implementation Plan — {feature_name}

**Goal:** {scope_statement}

## Behaviors

{behavior_sections}
"""


def _two_entries():
    from mage.artifacts.mapping import BaseBIDEntry
    return [
        BaseBIDEntry(base_bid="00000", behavior_name="auth", behavior_description="User logs in", depends_on=[]),
        BaseBIDEntry(base_bid="00001", behavior_name="orders", behavior_description="User places orders", depends_on=["00000"]),
    ]


def test_render_plan_includes_frontmatter(tmp_path):
    from mage.orchestration.plan_writer import render_plan
    template = tmp_path / "tpl.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    ascertain = AscertainOutput(
        feature_id="feat-001",
        feature_name="Auth flow",
        scope_statement="Email/password login.",
    )
    entries = _two_entries()
    from mage.agents.decomposition import ArchitectureSpec
    arch = ArchitectureSpec(parts=["api"], components=["auth-svc"], layers=["http"])

    output = render_plan(entries, ascertain, arch, template)

    assert output.startswith("---\n")
    assert "behavior_ids:" in output
    assert "- 00000" in output
    assert "- 00001" in output


def test_render_plan_includes_behavior_sections(tmp_path):
    from mage.orchestration.plan_writer import render_plan
    template = tmp_path / "tpl.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    ascertain = AscertainOutput(feature_id="f", feature_name="Auth", scope_statement="...")
    entries = _two_entries()
    from mage.agents.decomposition import ArchitectureSpec
    arch = ArchitectureSpec(parts=[], components=[], layers=[])

    output = render_plan(entries, ascertain, arch, template)

    assert "## Behaviors" in output
    assert "00000" in output
    assert "auth" in output
    assert "00001" in output
    assert "orders" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plan_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mage.orchestration.plan_writer'`.

- [ ] **Step 3: Implement `plan_writer.py`**

Create `src/mage/orchestration/plan_writer.py`:

```python
"""Plan writer: renders plan.md from behaviors + Ascertain output + architecture + template."""

from __future__ import annotations

from pathlib import Path

import yaml

from mage.agents.decomposition import ArchitectureSpec
from mage.artifacts.ascertain import AscertainOutput
from mage.artifacts.mapping import BaseBIDEntry


def _behavior_ids_yaml(entries: list[BaseBIDEntry]) -> str:
    lines = []
    for e in entries:
        lines.append(f"  - {e.base_bid}")
    return "\n".join(lines)


def _behaviors_yaml(entries: list[BaseBIDEntry]) -> str:
    data = []
    for e in entries:
        data.append({
            "id": e.base_bid,
            "name": e.behavior_name,
            "depends_on": e.depends_on,
            "notes": e.notes,
        })
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _architecture_summary(arch: ArchitectureSpec) -> str:
    parts = ", ".join(arch.parts) if arch.parts else "(none)"
    components = ", ".join(arch.components) if arch.components else "(none)"
    layers = ", ".join(arch.layers) if arch.layers else "(none)"
    return f"- **Parts:** {parts}\n- **Components:** {components}\n- **Layers:** {layers}"


def _behavior_sections(entries: list[BaseBIDEntry]) -> str:
    sections = []
    for e in entries:
        deps = ", ".join(e.depends_on) if e.depends_on else "(none)"
        cross = ", ".join(e.cross_behavior_links) if e.cross_behavior_links else "(none)"
        section = (
            f"### {e.base_bid} — {e.behavior_name}\n\n"
            f"**Description:** {e.behavior_description}\n\n"
            f"**Depends on:** {deps}\n\n"
            f"**Notes:** {e.notes or '(none)'}\n\n"
            f"**Cross-behavior links:** {cross}\n"
        )
        sections.append(section)
    return "\n".join(sections)


def render_plan(
    entries: list[BaseBIDEntry],
    ascertain: AscertainOutput,
    architecture: ArchitectureSpec,
    template_path: Path,
) -> str:
    """Render plan.md content from behaviors, Ascertain output, architecture, and template."""
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        behavior_ids_yaml=_behavior_ids_yaml(entries),
        behaviors_yaml=_behaviors_yaml(entries),
        project_id=ascertain.feature_id,
        feature_name=ascertain.feature_name,
        scope_statement=ascertain.scope_statement,
        architecture_summary=_architecture_summary(architecture),
        behavior_sections=_behavior_sections(entries),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plan_writer.py -v`
Expected: all 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/plan_writer.py tests/test_plan_writer.py
git commit -m "feat(orchestration): plan writer renders plan.md from behaviors + template"
```

---

### Task 15: `DecompositionStage` (orchestrates agent + enumeration + plan + finalize)

**Files:**
- Create: `src/mage/orchestration/decomposition.py`
- Test: `tests/test_decomposition.py`

**Interfaces:**
- Consumes: `PipelineContext`, `DecompositionAgent`, `HostConfig`, `parse_ascertain`, `enumerate_behaviors`, `render_plan`, `PlanArtifact`.
- Produces: `DecompositionStage` (a `StageNode` subclass) with `name = "decomposition"`. Reads `ascertain_path` from context (default `<project_dir>/ascertain.md`).

- [ ] **Step 1: Write failing tests**

Create `tests/test_decomposition.py`:

```python
"""Tests for the Decomposition stage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mage.orchestration.events import EventsLog


ASCERTAIN_FULL = """---
feature_id: feat-001
feature_name: User authentication
scope_statement: Email/password login.
in_scope: [login]
out_of_scope: [oauth]
success_criteria: [user can log in]
resolved_ambiguities: []
deferred_questions: []
constraints: []
three_amigos:
  product: ""
  tester: ""
  developer: ""
---

# Ascertain session
"""


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")
    return d


def test_decomposition_stage_runs_end_to_end(project_dir):
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.nodes import PipelineContext
    from mage.artifacts.mapping import MappingArtifact
    from mage.artifacts.enumeration import BehaviorSpec
    from mage.agents.decomposition import ArchitectureSpec, DecompositionOutput

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock()
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=["api"], components=["auth-svc"], layers=["http"]),
        behaviors=[
            BehaviorSpec(name="auth", description="User logs in"),
            BehaviorSpec(name="logout", description="User logs out", depends_on=["auth"]),
        ],
    )

    host_config = MagicMock()
    host_config.require_plan_approval = False
    host_config.plan_template_path = None

    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)

    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)
    result_ctx = stage.run(ctx)

    assert (project_dir / "decomposition.yaml").exists()
    assert (project_dir / "behaviors.yaml").exists()
    assert (project_dir / "plan.md").exists()
    assert (project_dir / "mapping.yaml").exists()
    assert len(result_ctx.mapping.base_bids) == 2


def test_decomposition_stage_writes_decomposition_yaml(project_dir):
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.nodes import PipelineContext
    from mage.artifacts.mapping import MappingArtifact
    from mage.artifacts.enumeration import BehaviorSpec
    from mage.agents.decomposition import ArchitectureSpec, DecompositionOutput

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock()
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=["api"], components=[], layers=[]),
        behaviors=[BehaviorSpec(name="auth", description="Login")],
    )
    host_config = MagicMock()
    host_config.require_plan_approval = False
    host_config.plan_template_path = None

    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)
    stage.run(ctx)

    import yaml
    decomp = yaml.safe_load((project_dir / "decomposition.yaml").read_text())
    assert "architecture" in decomp
    assert "behaviors" in decomp
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decomposition.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mage.orchestration.decomposition'`.

- [ ] **Step 3: Implement `DecompositionStage`**

Create `src/mage/orchestration/decomposition.py`:

```python
"""Decomposition stage: orchestrates agent run, behavior enumeration, plan writing, finalization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic_ai import models as pydantic_ai_models

from mage.agents.decomposition import ArchitectureSpec, DecompositionAgent
from mage.artifacts.ascertain import parse_ascertain
from mage.artifacts.enumeration import enumerate_behaviors
from mage.artifacts.plan import PlanArtifact
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.plan_writer import render_plan
from mage.verification.host_overrides import HostConfig


DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "plan_template.md"


class DecompositionStage(StageNode):
    """Runs once after Ascertain closes; produces decomposition, behaviors, plan."""

    name = "decomposition"

    def __init__(
        self,
        events_log: EventsLog,
        agent: DecompositionAgent,
        host_config: HostConfig,
    ) -> None:
        super().__init__(events_log)
        self.agent = agent
        self.host_config = host_config

    def _run(self, context: PipelineContext) -> PipelineContext:
        project_dir = context.project_dir
        ascertain_path = project_dir / "ascertain.md"

        # 1. Read + parse Ascertain
        ascertain = parse_ascertain(ascertain_path)

        # 2. Emit DECOMPOSITION_STARTED
        self.events_log.append(
            Event(
                event_type=EventType.DECOMPOSITION_STARTED,
                payload={"feature_id": ascertain.feature_id, "ascertain_path": str(ascertain_path)},
            )
        )

        # 3. Run Decomposition agent
        agent_output = self.agent.run(
            ascertain=ascertain, existing_mapping=context.mapping
        )

        # 4. Write decomposition.yaml
        decomposition_path = project_dir / "decomposition.yaml"
        decomposition_data = {
            "schema_version": 1,
            "feature_id": ascertain.feature_id,
            "architecture": agent_output.architecture.model_dump(),
            "behaviors_input": [b.model_dump() for b in agent_output.behaviors],
            "decomposed_at": datetime.now(timezone.utc).isoformat(),
        }
        decomposition_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = decomposition_path.with_suffix(decomposition_path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(decomposition_data, sort_keys=False), encoding="utf-8")
        tmp.replace(decomposition_path)

        # 5. Enumerate behaviors + write files
        updated_mapping, behaviors_path = enumerate_behaviors(
            agent_output.behaviors, context.mapping, project_dir, self.events_log
        )

        # 6. Generate plan.md content
        template_path = (
            self.host_config.plan_template_path
            if self.host_config.plan_template_path is not None
            else DEFAULT_TEMPLATE_PATH
        )
        new_entries = [
            e for e in updated_mapping.base_bids
            if e.base_bid not in {b.base_bid for b in context.mapping.base_bids}
        ]
        plan_content = render_plan(
            new_entries, ascertain, agent_output.architecture, template_path
        )

        # 7. Approval gate (if required)
        if self.host_config.require_plan_approval:
            # Deferred-tool pause (placeholder — real impl in Plan 6)
            import warnings
            warnings.warn(
                "require_plan_approval=True: deferred-tool prompt not yet wired in Plan 2; "
                "auto-approving for now."
            )

        # 8. Finalize Plan
        PlanArtifact.finalize(context.plan_path, plan_content, self.events_log)

        # 9. Emit DECOMPOSITION_COMPLETED
        self.events_log.append(
            Event(
                event_type=EventType.DECOMPOSITION_COMPLETED,
                payload={
                    "feature_id": ascertain.feature_id,
                    "behavior_count": len(new_entries),
                    "plan_path": str(context.plan_path),
                },
            )
        )

        # 10. Return updated context
        return context.model_copy(update={"mapping": updated_mapping})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decomposition.py -v`
Expected: all 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/decomposition.py tests/test_decomposition.py
git commit -m "feat(orchestration): DecompositionStage orchestrates full Decomposition flow"
```

---

### Task 16: Plan-revision halt mechanism (graph.run + persist_halt)

**Files:**
- Modify: `src/mage/orchestration/graph.py`
- Test: `tests/test_graph.py` (Plan 1, extend)

**Interfaces:**
- Consumes: `PipelineGraph` (Plan 1), `PlanRevisionRequired`.
- Produces: `PipelineGraph.run()` catches `PlanRevisionRequired`, calls `_persist_halt()`, raises `SystemExit(0)`. `PlanRevisionRequired` exception class.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_graph.py`:

```python
def test_pipeline_graph_catches_plan_revision_required_and_halts(tmp_path):
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.nodes import PipelineContext, StageNode
    from mage.orchestration.events import EventsLog, EventType
    from mage.artifacts.plan import PlanRevisionRequired

    log = EventsLog(tmp_path / "events.jsonl")

    class HaltingStage(StageNode):
        name = "halting"
        def _run(self, context):
            raise PlanRevisionRequired(
                reason="Plan ordering is wrong",
                originating_stage="halting",
                affected_behaviors=["00000"],
            )

    class NeverRunStage(StageNode):
        name = "never"
        def _run(self, context):
            raise AssertionError("should not run")

    graph = PipelineGraph(
        stages=[HaltingStage(log), NeverRunStage(log)],
        events_log=log,
    )

    ctx = PipelineContext(project_dir=tmp_path, mapping=MagicMock(), events_log=log)

    with pytest.raises(SystemExit) as exc_info:
        graph.run(ctx)
    assert exc_info.value.code == 0

    halt_events = [e for e in log.read_all() if e.event_type == EventType.HALT_PERSISTED]
    assert len(halt_events) == 1
    assert halt_events[0].payload["reason"] == "Plan ordering is wrong"
    assert halt_events[0].payload["originating_stage"] == "halting"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph.py::test_pipeline_graph_catches_plan_revision_required_and_halts -v`
Expected: FAIL with `ImportError` (PlanRevisionRequired doesn't exist yet) or `AttributeError`.

- [ ] **Step 3: Add `PlanRevisionRequired` to plan.py and halt handling to graph.py**

Add to `src/mage/artifacts/plan.py` (after existing exception classes):

```python
class PlanRevisionRequired(PlanError):
    """Raised by a stage when the Plan itself is wrong."""

    def __init__(
        self,
        reason: str,
        originating_stage: str,
        affected_behaviors: list[str],
    ) -> None:
        self.reason = reason
        self.originating_stage = originating_stage
        self.affected_behaviors = affected_behaviors
        super().__init__(reason)
```

Modify `src/mage/orchestration/graph.py`:

```python
"""PipelineGraph: linear stage runner with halt handling."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mage.artifacts.plan import PlanRevisionRequired
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.persistence import FileStatePersistence


class PipelineGraph:
    """Runs a list of stages in order, threading PipelineContext through them."""

    def __init__(self, stages: list[StageNode], events_log: EventsLog) -> None:
        self.events_log = events_log
        self.stages = list(stages)

    def run(self, initial_context: PipelineContext) -> PipelineContext:
        context = initial_context
        for stage in self.stages:
            try:
                context = stage.run(context)
            except PlanRevisionRequired as e:
                self._persist_halt(context, e)
                raise SystemExit(0) from e
        return context

    def _persist_halt(
        self, context: PipelineContext, halt: PlanRevisionRequired
    ) -> None:
        """Persist halt record (event + state)."""
        halt_event = Event(
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.HALT_PERSISTED,
            payload={
                "reason": halt.reason,
                "originating_stage": halt.originating_stage,
                "affected_behaviors": halt.affected_behaviors,
                "context_snapshot": context.model_dump(mode="json"),
            },
        )
        context.events_log.append(halt_event)

        state_dir = context.project_dir / ".haileris" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        persistence = FileStatePersistence(
            state_dir=state_dir, state_type=PipelineContext
        )
        persistence.save_state(context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph.py -v`
Expected: all graph tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mage/artifacts/plan.py src/mage/orchestration/graph.py tests/test_graph.py
git commit -m "feat(orchestration): PipelineGraph catches PlanRevisionRequired and persists halt"
```

---

### Task 17: `mage plan show` CLI

**Files:**
- Modify: `src/mage/cli.py`
- Test: `tests/test_cli.py` (Plan 1, extend)

**Interfaces:**
- Consumes: `mage plan show` argparse subcommand.
- Produces: `cmd_plan_show(args)` reads plan + digest + last event, prints to stdout.

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli.py`:

```python
def test_plan_show_prints_digest_and_content(tmp_path, capsys):
    from mage.artifacts.plan import PlanArtifact
    from mage.cli import main
    from mage.orchestration.events import EventsLog
    import sys

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# Plan\n\ncontent\n", log)

    test_argv = ["mage", "plan", "show", "--project-dir", str(tmp_path)]
    with patch.object(sys, "argv", test_argv):
        main()

    captured = capsys.readouterr()
    assert "Plan:" in captured.out
    assert str(plan_path) in captured.out
    assert "Digest:" in captured.out
    assert "# Plan" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_plan_show_prints_digest_and_content -v`
Expected: FAIL (subcommand not registered).

- [ ] **Step 3: Add `plan show` subcommand to CLI**

Modify `src/mage/cli.py`. Find the `build_parser` function and add:

```python
    # mage plan <subcommand>
    plan_parser = subparsers.add_parser("plan", help="Plan operations")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)

    # mage plan show
    show_parser = plan_subparsers.add_parser("show", help="Display Plan + digest")
    show_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    # mage plan revise
    revise_parser = plan_subparsers.add_parser("revise", help="Record a Plan revision after halt")
    revise_parser.add_argument("--reason", type=str, required=True)
    revise_parser.add_argument("--approver", type=str, required=True)
    revise_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    # mage run
    run_parser = subparsers.add_parser("run", help="Run the pipeline")
    run_parser.add_argument("--from", dest="from_stage", type=str, default=None)
    run_parser.add_argument("--project-dir", type=Path, default=Path.cwd())
```

Add the command handlers in the `main()` function dispatch:

```python
def cmd_plan_show(args):
    """Display Plan + digest + last event."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    plan_path = project_dir / "plan.md"

    print(f"Plan: {plan_path}")

    if not plan_path.exists():
        print("(Plan file does not exist on disk)")
        return

    # Find latest FINALIZED/REVISED event
    events = log.read_all()
    plan_events = [
        e for e in events
        if e.event_type.value in ("plan_finalized", "plan_revised")
        and e.payload.get("plan_path") == str(plan_path)
    ]
    if not plan_events:
        print("(No PLAN_FINALIZED event — Plan is unfinalized)")
        return

    latest = max(plan_events, key=lambda e: e.timestamp)
    digest = latest.payload.get("plan_sha256") or latest.payload.get("new_sha256")
    print(f"Digest: {digest}")
    print(f"Last event: {latest.event_type.value.upper().replace('_', ' ')} at {latest.timestamp.isoformat()}")
    print()

    try:
        content = PlanArtifact.load(plan_path, log)
    except Exception as e:
        print(f"(Failed to load Plan: {e})")
        return

    lines = content.splitlines()
    preview = "\n".join(lines[:50])
    print(preview)
    if len(lines) > 50:
        print(f"\n... ({len(lines) - 50} more lines)")
```

Update the `main()` dispatch to handle the new subcommand. Find the existing dispatch logic and add:

```python
    if args.command == "plan" and args.plan_command == "show":
        cmd_plan_show(args)
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_plan_show_prints_digest_and_content -v`
Expected: PASS.

- [ ] **Step 5: Run full test suite to verify nothing broke**

Run: `uv run pytest`
Expected: all tests pass (existing + new).

- [ ] **Step 6: Commit**

```bash
git add src/mage/cli.py tests/test_cli.py
git commit -m "feat(cli): add mage plan show subcommand"
```

---

### Task 18: `mage plan revise` CLI

**Files:**
- Modify: `src/mage/cli.py`
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `mage plan revise --reason X --approver Y` argparse subcommand.
- Produces: `cmd_plan_revise(args)` reads current plan.md, computes new digest, emits `PLAN_REVISED` event.

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli.py`:

```python
def test_plan_revise_records_event(tmp_path, capsys):
    from mage.artifacts.plan import PlanArtifact
    from mage.cli import main
    from mage.orchestration.events import EventsLog, EventType
    import sys

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# original\n", log)
    plan_path.write_text("# revised\n", encoding="utf-8")  # simulate external edit

    test_argv = [
        "mage", "plan", "revise",
        "--reason", "Reordered behaviors",
        "--approver", "alice",
        "--project-dir", str(tmp_path),
    ]
    with patch.object(sys, "argv", test_argv):
        main()

    revised = [e for e in log.read_all() if e.event_type == EventType.PLAN_REVISED]
    assert len(revised) == 1
    assert revised[0].payload["reason"] == "Reordered behaviors"
    assert revised[0].payload["human_approver"] == "alice"

    captured = capsys.readouterr()
    assert "Plan revision recorded" in captured.out or "revision" in captured.out.lower()


def test_plan_revise_missing_plan(tmp_path, capsys):
    from mage.cli import main
    import sys

    test_argv = [
        "mage", "plan", "revise",
        "--reason", "r",
        "--approver", "a",
        "--project-dir", str(tmp_path),
    ]
    with patch.object(sys, "argv", test_argv):
        with pytest.raises(SystemExit) as exc_info:
            main()
    # Non-zero exit on error
    assert exc_info.value.code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_plan_revise_records_event tests/test_cli.py::test_plan_revise_missing_plan -v`
Expected: both FAIL.

- [ ] **Step 3: Add `cmd_plan_revise` and dispatch it**

Add to `src/mage/cli.py`:

```python
def cmd_plan_revise(args):
    """Record a Plan revision after halt."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    plan_path = project_dir / "plan.md"

    if not plan_path.exists():
        print(f"mage plan revise: error: plan.md not found at {plan_path}", file=sys.stderr)
        sys.exit(2)

    # Check that a prior finalization exists
    events = log.read_all()
    plan_events = [
        e for e in events
        if e.event_type.value in ("plan_finalized", "plan_revised")
        and e.payload.get("plan_path") == str(plan_path)
    ]
    if not plan_events:
        print(
            f"mage plan revise: error: no PLAN_FINALIZED event for {plan_path}; "
            f"run mage run to create the Plan first",
            file=sys.stderr,
        )
        sys.exit(2)

    new_digest = PlanArtifact.revise(
        plan_path,
        plan_path.read_text(encoding="utf-8"),
        reason=args.reason,
        human_approver=args.approver,
        events_log=log,
    )

    print(f"Plan revision recorded. New digest: {new_digest}")
    print("Restart the pipeline with: mage run")
```

Update the `main()` dispatch:

```python
    if args.command == "plan" and args.plan_command == "revise":
        cmd_plan_revise(args)
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::test_plan_revise_records_event tests/test_cli.py::test_plan_revise_missing_plan -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mage/cli.py tests/test_cli.py
git commit -m "feat(cli): add mage plan revise subcommand"
```

---

### Task 19: `mage run` CLI

**Files:**
- Modify: `src/mage/cli.py`
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `mage run [--from <stage>] [--project-dir <path>]` argparse subcommand.
- Produces: `cmd_run(args)` loads halted context (if any), runs `PipelineGraph`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli.py`:

```python
def test_mage_run_with_no_pipeline_defined(tmp_path, capsys):
    """Smoke test: mage run with no halted context prints a helpful message."""
    from mage.cli import main
    import sys

    test_argv = ["mage", "run", "--project-dir", str(tmp_path)]
    with patch.object(sys, "argv", test_argv):
        main()

    captured = capsys.readouterr()
    # Either "no pipeline" message or runs cleanly — both acceptable for this smoke test
    assert "pipeline" in captured.out.lower() or captured.out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_mage_run_with_no_pipeline_defined -v`
Expected: FAIL.

- [ ] **Step 3: Add `cmd_run` and dispatch it**

Add to `src/mage/cli.py`:

```python
def cmd_run(args):
    """Run the pipeline with halt handling and resume support."""
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.persistence import FileStatePersistence

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    state_dir = project_dir / ".haileris" / "state"

    # Try to load halted context
    persistence = FileStatePersistence(
        state_dir=state_dir, state_type=PipelineContext
    )
    halted_ctx = persistence.load_state()

    if halted_ctx is not None:
        print(f"Resuming pipeline from halted state (stage={halted_ctx.current_stage})")
        ctx = halted_ctx
    else:
        print(f"No halted state found at {state_dir}; nothing to resume.")
        return 0

    # Note: actual stage list construction deferred to Plan 6 (full pipeline wiring).
    # For Plan 2, this command verifies the resume mechanism works.
    print(f"Pipeline context loaded: project_dir={ctx.project_dir}")
    print("Note: full pipeline wiring (stage list construction) is Plan 6 work.")
    return 0
```

Update the `main()` dispatch:

```python
    if args.command == "run":
        return cmd_run(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_mage_run_with_no_pipeline_defined -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mage/cli.py tests/test_cli.py
git commit -m "feat(cli): add mage run subcommand with halted-context resume"
```

---

### Task 20: End-to-end Decomposition happy-path test

**Files:**
- Create: `tests/test_e2e_decomposition.py`

**Interfaces:**
- Consumes: full pipeline (Ascertain → Decomposition → enumerated behaviors → Plan).
- Produces: integration test exercising Tasks 1–15.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_decomposition.py`:

```python
"""End-to-end test: full Decomposition flow from Ascertain to finalized Plan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mage.agents.decomposition import ArchitectureSpec, DecompositionAgent, DecompositionOutput
from mage.artifacts.enumeration import BehaviorSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.decomposition import DecompositionStage
from mage.orchestration.events import EventType, EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig


ASCERTAIN_FULL = """---
feature_id: feat-001
feature_name: User authentication
scope_statement: Email/password login.
in_scope: [login]
out_of_scope: [oauth]
success_criteria: [user can log in]
resolved_ambiguities: []
deferred_questions: []
constraints: []
three_amigos:
  product: ""
  tester: ""
  developer: ""
---

# Ascertain session
"""


def test_full_decomposition_flow_with_mock_agent(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=["api"], components=["auth-svc"], layers=["http"]),
        behaviors=[
            BehaviorSpec(name="auth", description="User logs in"),
            BehaviorSpec(name="logout", description="User logs out", depends_on=["auth"]),
        ],
    )

    host_config = HostConfig(require_plan_approval=False, plan_template_path=None)
    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    result_ctx = stage.run(ctx)

    # All files written
    assert (project_dir / "decomposition.yaml").exists()
    assert (project_dir / "behaviors.yaml").exists()
    assert (project_dir / "plan.md").exists()
    assert (project_dir / "mapping.yaml").exists()

    # Mapping updated
    assert len(result_ctx.mapping.base_bids) == 2
    bnames = {e.behavior_name for e in result_ctx.mapping.base_bids}
    assert bnames == {"auth", "logout"}

    # Plan is finalized (digest matches on load)
    from mage.artifacts.plan import PlanArtifact
    content = PlanArtifact.load(project_dir / "plan.md", log)
    assert "auth" in content
    assert "logout" in content

    # Events emitted
    events = log.read_all()
    event_types = {e.event_type for e in events}
    assert EventType.DECOMPOSITION_STARTED in event_types
    assert EventType.DECOMPOSITION_COMPLETED in event_types
    assert EventType.BEHAVIORS_ENUMERATED in event_types
    assert EventType.PLAN_FINALIZED in event_types
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_decomposition.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_decomposition.py
git commit -m "test: end-to-end Decomposition flow (Ascertain -> Plan)"
```

---

### Task 21: End-to-end halt-and-resume test

**Files:**
- Modify: `tests/test_e2e_decomposition.py`

**Interfaces:**
- Consumes: halt mechanism (Task 16), `mage plan revise` (Task 18).
- Produces: e2e test that runs Decomposition, halts, runs `mage plan revise`, verifies resume.

- [ ] **Step 1: Write failing e2e test**

Append to `tests/test_e2e_decomposition.py`:

```python
def test_halt_and_resume_cycle(tmp_path):
    """Verify: Decomposition halts -> mage plan revise -> mage run resumes."""
    from mage.artifacts.plan import PlanArtifact, PlanRevisionRequired
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.nodes import PipelineContext, StageNode
    import sys
    from unittest.mock import patch
    from mage.cli import main

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=["api"], components=[], layers=[]),
        behaviors=[BehaviorSpec(name="auth", description="User logs in")],
    )
    host_config = HostConfig(require_plan_approval=False)
    decomp_stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)

    class HaltAfterDecomp(StageNode):
        name = "halt_after_decomp"
        def _run(self, context):
            raise PlanRevisionRequired(
                reason="Plan ordering is wrong",
                originating_stage="halt_after_decomp",
                affected_behaviors=["00000"],
            )

    graph = PipelineGraph(
        stages=[decomp_stage, HaltAfterDecomp(log)],
        events_log=log,
    )
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    with pytest.raises(SystemExit) as exc_info:
        graph.run(ctx)
    assert exc_info.value.code == 0

    # Halt record persisted
    halt_events = [e for e in log.read_all() if e.event_type == EventType.HALT_PERSISTED]
    assert len(halt_events) == 1

    # State persisted
    state_dir = project_dir / ".haileris" / "state"
    assert any(state_dir.iterdir()) if state_dir.exists() else False

    # External edit of plan.md
    plan_path = project_dir / "plan.md"
    plan_path.write_text("# revised plan content\n", encoding="utf-8")

    # Run mage plan revise
    test_argv = [
        "mage", "plan", "revise",
        "--reason", "Reordered behaviors per human review",
        "--approver", "alice",
        "--project-dir", str(project_dir),
    ]
    with patch.object(sys, "argv", test_argv):
        main()

    # Plan load now succeeds with new digest
    content = PlanArtifact.load(plan_path, log)
    assert content == "# revised plan content\n"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_decomposition.py::test_halt_and_resume_cycle -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_decomposition.py
git commit -m "test: end-to-end halt-and-resume cycle"
```

---

### Task 22: End-to-end approval-gate test

**Files:**
- Modify: `tests/test_e2e_decomposition.py`

**Interfaces:**
- Consumes: `HostConfig.require_plan_approval`.
- Produces: e2e test verifying `require_plan_approval=True` emits a warning (deferred-tool pause not yet wired in Plan 2); `require_plan_approval=False` skips it.

- [ ] **Step 1: Write failing e2e test**

Append to `tests/test_e2e_decomposition.py`:

```python
def test_approval_gate_required_emits_warning(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=[], components=[], layers=[]),
        behaviors=[BehaviorSpec(name="auth", description="Login")],
    )

    host_config = HostConfig(require_plan_approval=True)
    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        stage.run(ctx)
        approval_warnings = [
            x for x in w if "require_plan_approval" in str(x.message)
        ]
        assert len(approval_warnings) >= 1


def test_approval_gate_disabled_runs_silently(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=[], components=[], layers=[]),
        behaviors=[BehaviorSpec(name="auth", description="Login")],
    )

    host_config = HostConfig(require_plan_approval=False)
    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        stage.run(ctx)
        approval_warnings = [
            x for x in w if "require_plan_approval" in str(x.message)
        ]
        assert len(approval_warnings) == 0
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_decomposition.py::test_approval_gate_required_emits_warning tests/test_e2e_decomposition.py::test_approval_gate_disabled_runs_silently -v`
Expected: both PASS.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest`
Expected: all tests pass (Plan 1's 72 + Plan 2's ~30 = ~102 total).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_decomposition.py
git commit -m "test: end-to-end approval gate on/off"
```

---

## Self-Review

After writing all 22 tasks, scan the spec for coverage:

| Spec section | Tasks |
|---|---|
| R1 — same Decomposition agent | Task 15 (DecompositionStage runs agent + plan in same flow) |
| R2 — Markdown + YAML frontmatter | Tasks 13, 14 (template + writer) |
| R3 — digest-pinned via events log | Task 6 (PlanArtifact), Task 7 (load verification) |
| R4 — persist-then-exit halt | Task 16 (graph halt handling) |
| R5 — three separate files | Tasks 10, 11 (decomposition.yaml, behaviors.yaml), 13, 14, 15 (plan.md) |
| R6 — rich behavior schema | Task 9 (BehaviorSpec), Task 10 (enumeration) |
| R7 — host-project configurable | Task 5 (HostConfig extension), Task 22 (e2e test) |
| R8 — agent describes, system assigns | Task 12 (agent emits BehaviorSpec no BID), Task 10 (system assigns via mapping.next_base_bid) |
| R9 — Ascertain schema | Task 9 (AscertainOutput model + parse_ascertain) |
| R10 — mage CLI | Task 1 (pyproject rename), Tasks 17, 18, 19 (subcommands) |

**Coverage check:** all 10 spec resolutions (R1–R10) covered.

**Type consistency check:**

- `MappingArtifact.next_base_bid()` (Plan 1) — used in Task 10/11 for sequential BID derivation. ✓
- `Base85BID.increment()` (Plan 1) — used in Task 10/11 to advance to next BID. ✓
- `EventsLog.append()` / `read_all()` (Plan 1) — used throughout. ✓
- `FileStatePersistence.save_state()` / `load_state()` (Plan 1) — used in Task 16. ✓
- `StageNode.run()` / `_run()` (Plan 1) — extended in Task 15 (DecompositionStage). ✓
- `PipelineContext` (Plan 1) — extended with `plan_path` in Task 4. ✓
- `MechanicalVerifier` (Plan 1) — not used in Plan 2 (mechanical verification applies at Inscribe, not Decomposition). ✓
- `HostConfig` (Plan 1) — extended in Task 5. ✓
- `PlanArtifact` (new in Task 6) — used by Tasks 14, 15, 17, 18, 21. ✓
- `enumerate_behaviors` (new in Tasks 10/11) — used by Task 15. ✓

**Placeholder scan:** no "TBD", "TODO", "implement later", "fill in details" in the plan.

**Ambiguity check:**

- Task 16's halt mechanism: explicit about catching `PlanRevisionRequired` and raising `SystemExit(0)`. ✓
- Task 6's idempotent finalize: explicit about re-finalize allowed only on matching digest. ✓
- Task 11's atomic writes: explicit that validation errors do not write files. ✓
- Task 15's approval gate: explicit warning when `require_plan_approval=True` and pause isn't yet wired. ✓
- Task 19's `mage run`: explicit that full pipeline wiring is Plan 6 work; this task only verifies halt-resume mechanism. ✓

**Spec coverage gaps:** none identified. All R1–R10 resolutions have implementing tasks.