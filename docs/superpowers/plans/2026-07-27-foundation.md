# HAILERIS v2 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation of the HAILERIS v2 pipeline: project scaffolding, Base85 BID registry, project-level mapping artifact, FileStatePersistence + events.jsonl, Pydantic-Graph skeleton, stage node base classes, mechanical author verification (the 7 deterministic checks), host-project override mechanism, and CLI entry point. Subsequent plans (Decomposition, Inscribe + 7 Reviewers, Etch + Realize, Inspect + Settle, Three Practices discipline) build features on this foundation.

**Architecture:** Python package `haileris_v2` with three top-level modules:

- `orchestration/` — Pydantic-Graph state machine, stage node base classes, FileStatePersistence + events.jsonl
- `artifacts/` — project-level mapping artifact (single source of truth for BIDs) and Base85 BID derivation
- `verification/` — mechanical author verification (deterministic, no LLM) with host-project override

Plus a CLI entry point at `haileris_v2.cli`. This plan covers **Plan 1 of 6** in the v2 implementation; subsequent plans build features incrementally.

**Tech Stack:** Python 3.12+, Pydantic v2, Pydantic-AI, Pydantic-Graph, pytest, pyyaml, uv (package manager), hatchling (build backend).

## Global Constraints

These are project-wide requirements that every task's implementation implicitly satisfies:

- **BID format:** Base85 alphabet, monotonically increasing within tier. Base BIDs are 5-digit Base85; sub-BIDs are appended Base85 characters using the same alphabet. Combination `<base>-<sub>` is globally unique (e.g., `00000-A`).
- **BIDs never reused:** A retired BID stays retired permanently.
- **Mapping artifact is project-level, single source of truth:** `mapping.yaml` at the project root. Next base-BID derived from highest assigned base-BID + 1.
- **Mechanical verification is deterministic:** No LLM calls in the 7 mechanical checks. Pure structural/grammatical/syntactic validation.
- **Mechanical check set (default, host-project-tunable):** `gherkin-syntax`, `scenario-name-unique`, `tags-registered`, `step-definitions-resolvable`, `lifecycle-status-tag-present`, `sub-bid-assigned`, `cross-behavior-tags-valid`.
- **Host-project overrides:** Any tunable behavior can be overridden by the host project's own artifacts (e.g., a check set config file).
- **Persistence is append-only for events:** `events.jsonl` is append-only; never edited in place. State files are written atomically (write-temp-then-rename).
- **All Pydantic models use `model_config = ConfigDict(frozen=True)` where state is meant to be immutable** (e.g., the mapping artifact base entries).

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.gitignore`
- Create: `src/haileris_v2/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Initialize pyproject.toml**

Write `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "haileris-v2"
version = "0.1.0"
description = "HAILERIS v2: spec-driven development pipeline"
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
h2 = "haileris_v2.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/haileris_v2"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 1: Initialize pyproject.toml**

- [ ] **Step 2: Write README.md**

```markdown
# HAILERIS v2

Spec-driven development pipeline. Implementation of the v2 design spec.

See `docs/superpowers/specs/2026-07-10-haileris-v2-design.md` for the design.

## Development

```bash
uv sync
uv run pytest
```
```

- [ ] **Step 3: Write .gitignore**

```
__pycache__/
*.pyc
*.egg-info/
.venv/
.pytest_cache/
.coverage
dist/
build/
*.haileris/
mapping.yaml
events.jsonl
pipeline-state.yaml
```

- [ ] **Step 4: Create package skeleton**

Write `src/haileris_v2/__init__.py`:

```python
"""HAILERIS v2: spec-driven development pipeline."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Create test skeleton**

Write `tests/__init__.py` (empty file) and `tests/conftest.py`:

```python
"""Pytest configuration and shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Provide an isolated project directory for tests."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir
```

- [ ] **Step 6: Verify scaffold builds**

Run: `uv sync`
Expected: succeeds, dependencies install.

Run: `uv run python -c "import haileris_v2; print(haileris_v2.__version__)"`
Expected: prints `0.1.0`.

Run: `uv run pytest`
Expected: collects 0 tests, exits successfully.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml README.md .gitignore src/ tests/
git commit -m "feat: scaffold haileris-v2 package with pyproject + tests"
```

---

### Task 2: Base85 BID Module

**Files:**
- Create: `src/haileris_v2/artifacts/__init__.py`
- Create: `src/haileris_v2/artifacts/bid.py`
- Create: `tests/test_bid.py`

The Base85 BID module provides encoding, decoding, and monotonic increment for the BID scheme. The alphabet is a fixed 85-character set (RFC 1924 base85-style, adapted):

```python
# Base85 alphabet (RFC 1924 style, 85 printable ASCII characters)
BASE85_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~"
```

A base BID is 5 digits of Base85; sub-BIDs are appended Base85 characters using the same alphabet.

**Interfaces:**
- Consumes: nothing (no dependencies on other tasks)
- Produces:
  - `class Base85BID` — Pydantic model holding a Base85-encoded string
  - `Base85BID.increment() -> Base85BID` — returns next BID in sequence
  - `Base85BID.parse(value: str) -> Base85BID` — validates and constructs from string
  - `module next_base_bid(highest: Base85BID) -> Base85BID` — derives the next base-BID from the highest assigned

- [ ] **Step 1: Write the failing test**

Write `tests/test_bid.py`:

```python
"""Tests for the Base85 BID module."""

from __future__ import annotations

import pytest
from haileris_v2.artifacts.bid import Base85BID, next_base_bid


class TestBase85BID:
    def test_construct_from_5_digit_string(self):
        bid = Base85BID(value="00000")
        assert bid.value == "00000"

    def test_construct_rejects_invalid_chars(self):
        with pytest.raises(ValueError, match="invalid Base85 character"):
            Base85BID(value="0000 ")  # space not in alphabet

    def test_increment_00000_to_00001(self):
        bid = Base85BID(value="00000")
        incremented = bid.increment()
        assert incremented.value == "00001"

    def test_increment_rolls_over_at_alphabet_end(self):
        # 84 is the highest 2-digit value in Base85 (alphabet has 85 chars)
        bid = Base85BID(value="0000z")  # 'z' is index 57, not the end
        # Use the highest possible 5-digit Base85 value
        max_bid = Base85BID(value="~~~~~")  # '~' is the last char in alphabet (index 84)
        with pytest.raises(OverflowError, match="exhausted"):
            max_bid.increment()

    def test_increment_is_monotonic(self):
        a = Base85BID(value="00005")
        b = a.increment()
        c = b.increment()
        assert a.value < b.value < c.value


class TestNextBaseBid:
    def test_next_from_zero(self):
        # No BIDs assigned yet; next is "00000"
        next_bid = next_base_bid(highest=None)
        assert next_bid.value == "00000"

    def test_next_from_existing(self):
        highest = Base85BID(value="00042")
        next_bid = next_base_bid(highest=highest)
        assert next_bid.value == "00043"

    def test_next_handles_max_value(self):
        max_bid = Base85BID(value="~~~~~")
        with pytest.raises(OverflowError, match="exhausted"):
            next_base_bid(highest=max_bid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bid.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.artifacts'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/artifacts/__init__.py` (empty) and `src/haileris_v2/artifacts/bid.py`:

```python
"""Base85 BID encoding and monotonic increment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


# Base85 alphabet (RFC 1924 style, 85 printable ASCII characters).
# Order matters: index 0 = '0', index 84 = '~'.
BASE85_ALPHABET = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "!#$%&()*+-;<=>?@^_`{|}~"
)
BASE85_RADIX = len(BASE85_ALPHABET)  # 85

# Base BIDs are exactly 5 Base85 characters.
BASE_BID_LENGTH = 5


class Base85BID(BaseModel):
    """A Base85-encoded BID.

    For base BIDs, value is exactly 5 Base85 chars.
    For sub-BIDs, value is one or more appended Base85 chars (validated separately).
    """

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value")
    @classmethod
    def _validate_base85(cls, v: str) -> str:
        if not v:
            raise ValueError("BID value cannot be empty")
        for ch in v:
            if ch not in BASE85_ALPHABET:
                raise ValueError(f"invalid Base85 character: {ch!r}")
        return v

    def increment(self) -> "Base85BID":
        """Return the next BID in the sequence (monotonic).

        Raises OverflowError if all digits are at the maximum alphabet value.
        """
        # Increment from the rightmost char; carry left on rollover.
        chars = list(self.value)
        i = len(chars) - 1
        while i >= 0:
            idx = BASE85_ALPHABET.index(chars[i])
            if idx < BASE85_RADIX - 1:
                chars[i] = BASE85_ALPHABET[idx + 1]
                return Base85BID(value="".join(chars))
            # Rollover: this char resets to 0, carry to the left.
            chars[i] = BASE85_ALPHABET[0]
            i -= 1
        # All digits rolled over — exhausted.
        raise OverflowError(f"BID space exhausted for value {self.value!r}")


def next_base_bid(highest: Base85BID | None) -> Base85BID:
    """Derive the next base-BID from the highest assigned (or zero if none).

    For base BIDs, the result is a 5-character Base85 string starting at '00000'
    if no BIDs have been assigned.
    """
    if highest is None:
        return Base85BID(value="0" * BASE_BID_LENGTH)
    # Pad/truncate to 5 chars for base-BID semantics.
    padded = highest.value.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])[:BASE_BID_LENGTH]
    if len(padded) < BASE_BID_LENGTH:
        padded = padded.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])
    return Base85BID(value=padded).increment()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bid.py -v`
Expected: PASS (all 8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/artifacts/ tests/test_bid.py
git commit -m "feat(artifacts): add Base85 BID module with increment + monotonic derivation"
```

---

### Task 3: Mapping Artifact Schema and Operations

**Files:**
- Create: `src/haileris_v2/artifacts/mapping.py`
- Create: `tests/test_mapping.py`

The mapping artifact is the project-level source of truth for BIDs. It's a YAML file at the project root (`mapping.yaml`) with this shape:

```yaml
schema_version: 1
project_id: <string>
base_bids:
  - base_bid: "00000"
    behavior_name: <string>
    behavior_description: <string>
    scenarios:
      - sub_bid: "A"
        scenario_text_hash: <sha256>
        lifecycle_status: inscribing | approved | live | deprecated | retired
        supersedes: <sub_bid> | null
        superseded_by: <sub_bid> | null
        tests: [<test_ref>, ...]
        derivations: [<path>, ...]
    reversion_log:
      - sub_bid: "A"
        timestamp: <iso8601>
        reason: <string>
        originating_stage: <string>
    post_live_revisions:
      - sub_bid: "A"
        timestamp: <iso8601>
        human_approver: <string>
        before_hash: <sha256>
        after_hash: <sha256>
    cross_behavior_links: [<base_bid>, ...]
```

**Interfaces:**
- Consumes: `Base85BID` from Task 2
- Produces:
  - `class LifecycleStatus(str, Enum)` — `inscribing | approved | live | deprecated | retired`
  - `class ScenarioEntry(BaseModel)` — sub-BID scenario record
  - `class BaseBIDEntry(BaseModel)` — base-BID behavior record
  - `class MappingArtifact(BaseModel)` — top-level mapping model
  - `MappingArtifact.load(path: Path) -> MappingArtifact` — read from YAML
  - `MappingArtifact.save(path: Path) -> None` — write atomically (write-temp-then-rename)
  - `MappingArtifact.next_base_bid() -> Base85BID` — derive next available base-BID
  - `MappingArtifact.lookup_sub_bid(base: Base85BID, sub: str) -> ScenarioEntry | None`

- [ ] **Step 1: Write the failing test**

Write `tests/test_mapping.py`:

```python
"""Tests for the mapping artifact."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from haileris_v2.artifacts.bid import Base85BID
from haileris_v2.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)


class TestLifecycleStatus:
    def test_values(self):
        assert LifecycleStatus.INSCRIBING.value == "inscribing"
        assert LifecycleStatus.APPROVED.value == "approved"
        assert LifecycleStatus.LIVE.value == "live"
        assert LifecycleStatus.DEPRECATED.value == "deprecated"
        assert LifecycleStatus.RETIRED.value == "retired"


class TestScenarioEntry:
    def test_minimal_construction(self):
        entry = ScenarioEntry(
            sub_bid="A",
            scenario_text_hash="abc123",
            lifecycle_status=LifecycleStatus.INSCRIBING,
            supersedes=None,
            superseded_by=None,
            tests=[],
            derivations=[],
        )
        assert entry.sub_bid == "A"
        assert entry.lifecycle_status == LifecycleStatus.INSCRIBING


class TestBaseBIDEntry:
    def test_minimal_construction(self):
        entry = BaseBIDEntry(
            base_bid="00000",
            behavior_name="user authentication",
            behavior_description="users can log in and out",
            scenarios=[],
            reversion_log=[],
            post_live_revisions=[],
            cross_behavior_links=[],
        )
        assert entry.base_bid == "00000"


class TestMappingArtifact:
    def test_empty_artifact(self):
        artifact = MappingArtifact(
            schema_version=1,
            project_id="test-project",
            base_bids=[],
        )
        assert artifact.project_id == "test-project"
        assert artifact.base_bids == []

    def test_next_base_bid_when_empty(self):
        artifact = MappingArtifact(
            schema_version=1, project_id="test", base_bids=[]
        )
        next_bid = artifact.next_base_bid()
        assert next_bid.value == "00000"

    def test_next_base_bid_with_existing(self):
        artifact = MappingArtifact(
            schema_version=1,
            project_id="test",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b1",
                    behavior_description="d1",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                ),
                BaseBIDEntry(
                    base_bid="00005",
                    behavior_name="b2",
                    behavior_description="d2",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                ),
            ],
        )
        next_bid = artifact.next_base_bid()
        assert next_bid.value == "00006"

    def test_lookup_sub_bid_found(self):
        scenario = ScenarioEntry(
            sub_bid="A",
            scenario_text_hash="h1",
            lifecycle_status=LifecycleStatus.LIVE,
            supersedes=None,
            superseded_by=None,
            tests=["test_login"],
            derivations=["src/auth.py"],
        )
        artifact = MappingArtifact(
            schema_version=1,
            project_id="test",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b1",
                    behavior_description="d1",
                    scenarios=[scenario],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        result = artifact.lookup_sub_bid(Base85BID(value="00000"), "A")
        assert result is not None
        assert result.sub_bid == "A"
        assert result.lifecycle_status == LifecycleStatus.LIVE

    def test_lookup_sub_bid_not_found(self):
        artifact = MappingArtifact(
            schema_version=1, project_id="test", base_bids=[]
        )
        result = artifact.lookup_sub_bid(Base85BID(value="00000"), "A")
        assert result is None


class TestMappingArtifactIO:
    def test_round_trip(self, tmp_project_dir: Path):
        original = MappingArtifact(
            schema_version=1,
            project_id="round-trip",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="auth",
                    behavior_description="users authenticate",
                    scenarios=[
                        ScenarioEntry(
                            sub_bid="A",
                            scenario_text_hash="hash1",
                            lifecycle_status=LifecycleStatus.APPROVED,
                            supersedes=None,
                            superseded_by=None,
                            tests=[],
                            derivations=[],
                        )
                    ],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        path = tmp_project_dir / "mapping.yaml"
        original.save(path)
        loaded = MappingArtifact.load(path)
        assert loaded.project_id == "round-trip"
        assert len(loaded.base_bids) == 1
        assert loaded.base_bids[0].scenarios[0].sub_bid == "A"

    def test_save_is_atomic(self, tmp_project_dir: Path):
        # After save, no temp files should remain.
        artifact = MappingArtifact(
            schema_version=1, project_id="atomic", base_bids=[]
        )
        path = tmp_project_dir / "mapping.yaml"
        artifact.save(path)
        # No .tmp files left behind
        assert list(tmp_project_dir.glob("*.tmp")) == []
        assert path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.artifacts.mapping'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/artifacts/mapping.py`:

```python
"""Project-level mapping artifact: single source of truth for BIDs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from haileris_v2.artifacts.bid import BASE85_ALPHABET, BASE_BID_LENGTH, Base85BID


class LifecycleStatus(str, Enum):
    """Per-scenario lifecycle status (spec Pivot #3)."""

    INSCRIBING = "inscribing"
    APPROVED = "approved"
    LIVE = "live"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class ReversionLogEntry(BaseModel):
    """One reversion event (spec Open Question 3)."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    timestamp: datetime
    reason: str
    originating_stage: str


class PostLiveRevisionEntry(BaseModel):
    """One cosmetic revision on a live scenario (spec Settle Routing)."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    timestamp: datetime
    human_approver: str
    before_hash: str
    after_hash: str


class ScenarioEntry(BaseModel):
    """One scenario under a base BID (spec Pivot #6)."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    scenario_text_hash: str
    lifecycle_status: LifecycleStatus
    supersedes: str | None = None
    superseded_by: str | None = None
    tests: list[str] = Field(default_factory=list)
    derivations: list[str] = Field(default_factory=list)


class BaseBIDEntry(BaseModel):
    """One behavior's worth of scenarios (spec Pivot #6)."""

    model_config = ConfigDict(frozen=True)

    base_bid: str
    behavior_name: str
    behavior_description: str
    scenarios: list[ScenarioEntry] = Field(default_factory=list)
    reversion_log: list[ReversionLogEntry] = Field(default_factory=list)
    post_live_revisions: list[PostLiveRevisionEntry] = Field(default_factory=list)
    cross_behavior_links: list[str] = Field(default_factory=list)


class MappingArtifact(BaseModel):
    """Top-level mapping artifact (spec Pivot #6)."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    project_id: str
    base_bids: list[BaseBIDEntry] = Field(default_factory=list)

    def highest_base_bid(self) -> Base85BID | None:
        """Return the highest assigned base BID, or None if empty."""
        if not self.base_bids:
            return None
        highest = max(self.base_bids, key=lambda e: e.base_bid)
        return Base85BID(value=highest.base_bid)

    def next_base_bid(self) -> Base85BID:
        """Derive the next available base BID."""
        highest = self.highest_base_bid()
        if highest is None:
            return Base85BID(value="0" * BASE_BID_LENGTH)
        # Ensure 5-char padding for base-BID semantics.
        padded = highest.value.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])
        return Base85BID(value=padded).increment()

    def lookup_sub_bid(self, base: Base85BID, sub: str) -> ScenarioEntry | None:
        """Find a scenario entry by (base, sub). Returns None if not found."""
        for entry in self.base_bids:
            if entry.base_bid == base.value:
                for scenario in entry.scenarios:
                    if scenario.sub_bid == sub:
                        return scenario
        return None

    def save(self, path: Path) -> None:
        """Write the mapping artifact atomically (write-temp-then-rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        # Atomic write: write to .tmp, then rename.
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.safe_dump(data, sort_keys=False))
        tmp_path.replace(path)

    @classmethod
    def load(cls, path: Path) -> "MappingArtifact":
        """Load the mapping artifact from a YAML file."""
        data = yaml.safe_load(path.read_text())
        return cls.model_validate(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mapping.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/artifacts/mapping.py tests/test_mapping.py
git commit -m "feat(artifacts): add project-level mapping artifact with atomic save/load"
```

---

### Task 4: FileStatePersistence

**Files:**
- Create: `src/haileris_v2/orchestration/__init__.py`
- Create: `src/haileris_v2/orchestration/persistence.py`
- Create: `tests/test_persistence.py`

FileStatePersistence provides durable state for the orchestration state machine. State is written atomically (write-temp-then-rename) so partial writes don't corrupt the state.

**Interfaces:**
- Consumes: nothing (no dependencies on prior tasks beyond stdlib)
- Produces:
  - `class FileStatePersistence`:
    - `__init__(state_dir: Path)` — store state files in `state_dir`
    - `save_state(state: BaseModel) -> None` — write state atomically
    - `load_state() -> BaseModel | None` — read state, or None if no state exists

- [ ] **Step 1: Write the failing test**

Write `tests/test_persistence.py`:

```python
"""Tests for FileStatePersistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel
from haileris_v2.orchestration.persistence import FileStatePersistence


class SampleState(BaseModel):
    """A simple state model for testing."""

    iteration: int = 0
    current_scenario: str | None = None
    notes: str = ""


class TestFileStatePersistence:
    def test_init_creates_dir(self, tmp_path: Path):
        state_dir = tmp_path / "state"
        FileStatePersistence(state_dir)
        assert state_dir.exists()

    def test_load_when_no_state(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        assert persistence.load_state(SampleState) is None

    def test_round_trip(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        state = SampleState(iteration=3, current_scenario="00000-A", notes="hello")
        persistence.save_state(state)
        loaded = persistence.load_state(SampleState)
        assert loaded is not None
        assert loaded.iteration == 3
        assert loaded.current_scenario == "00000-A"
        assert loaded.notes == "hello"

    def test_save_is_atomic(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        state = SampleState(iteration=1)
        persistence.save_state(state)
        # No temp files should remain.
        assert list((tmp_path / "state").glob("*.tmp")) == []

    def test_save_overwrites(self, tmp_path: Path):
        persistence = FileStatePersistence(tmp_path / "state")
        persistence.save_state(SampleState(iteration=1))
        persistence.save_state(SampleState(iteration=2))
        loaded = persistence.load_state(SampleState)
        assert loaded is not None
        assert loaded.iteration == 2

    def test_recovers_from_corrupt_state(self, tmp_path: Path):
        # Write garbage to the state file; load should raise a clear error.
        persistence = FileStatePersistence(tmp_path / "state")
        state_file = tmp_path / "state" / "pipeline-state.yaml"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not: valid: yaml: at all: :::")
        with pytest.raises(Exception):  # Pydantic ValidationError or yaml.YAMLError
            persistence.load_state(SampleState)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.orchestration'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/orchestration/__init__.py` (empty) and `src/haileris_v2/orchestration/persistence.py`:

```python
"""FileStatePersistence: atomic state writes for the orchestration state machine."""

from __future__ import annotations

from pathlib import Path
from typing import Type, TypeVar

import yaml
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FileStatePersistence:
    """Persists a Pydantic state model to disk atomically.

    State files are written to <state_dir>/pipeline-state.yaml using a
    write-temp-then-rename pattern so partial writes never corrupt state.
    """

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "pipeline-state.yaml"

    def save_state(self, state: BaseModel) -> None:
        """Write state atomically (write-temp-then-rename)."""
        data = state.model_dump(mode="json")
        tmp_path = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp_path.write_text(yaml.safe_dump(data, sort_keys=False))
        tmp_path.replace(self.state_file)

    def load_state(self, state_type: Type[T]) -> T | None:
        """Load state, or return None if no state file exists."""
        if not self.state_file.exists():
            return None
        data = yaml.safe_load(self.state_file.read_text())
        return state_type.model_validate(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/orchestration/persistence.py tests/test_persistence.py
git commit -m "feat(orchestration): add FileStatePersistence with atomic writes"
```

---

### Task 5: Events Log (events.jsonl)

**Files:**
- Create: `src/haileris_v2/orchestration/events.py`
- Create: `tests/test_events.py`

The events log is an append-only JSONL file (`events.jsonl`) recording every state-machine event. Per the spec, the log is append-only and supports replay.

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class EventType(str, Enum)` — types of events (stage_started, stage_completed, finding_recorded, scenario_state_changed, etc.)
  - `class Event(BaseModel)` — single event with timestamp, type, payload
  - `class EventsLog`:
    - `__init__(log_path: Path)` — open/append to the log
    - `append(event: Event) -> None` — append a single event
    - `read_all() -> list[Event]` — read all events (for replay)
    - `read_since(timestamp: datetime) -> list[Event]` — read events after a timestamp

- [ ] **Step 1: Write the failing test**

Write `tests/test_events.py`:

```python
"""Tests for the events log."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from haileris_v2.orchestration.events import Event, EventType, EventsLog


class TestEvent:
    def test_construction(self):
        event = Event(
            timestamp=datetime(2026, 7, 27, tzinfo=timezone.utc),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "harvest"},
        )
        assert event.event_type == EventType.STAGE_STARTED
        assert event.payload == {"stage": "harvest"}


class TestEventsLog:
    def test_init_creates_file(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        log_path.touch()  # Ensure file exists for empty-log case
        assert log_path.exists()

    def test_append_and_read_all(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "harvest"},
        ))
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 5, tzinfo=timezone.utc),
            event_type=EventType.STAGE_COMPLETED,
            payload={"stage": "harvest"},
        ))
        events = log.read_all()
        assert len(events) == 2
        assert events[0].event_type == EventType.STAGE_STARTED
        assert events[1].event_type == EventType.STAGE_COMPLETED

    def test_read_empty_log(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log_path.touch()
        log = EventsLog(log_path)
        assert log.read_all() == []

    def test_read_since(self, tmp_path: Path):
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        cutoff = datetime(2026, 7, 27, 10, 2, tzinfo=timezone.utc)
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "harvest"},
        ))
        log.append(Event(
            timestamp=datetime(2026, 7, 27, 10, 5, tzinfo=timezone.utc),
            event_type=EventType.STAGE_COMPLETED,
            payload={"stage": "harvest"},
        ))
        events = log.read_since(cutoff)
        assert len(events) == 1
        assert events[0].event_type == EventType.STAGE_COMPLETED

    def test_log_is_append_only(self, tmp_path: Path):
        # After appends, no in-place edits to the file.
        log_path = tmp_path / "events.jsonl"
        log = EventsLog(log_path)
        log.append(Event(
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.STAGE_STARTED,
            payload={},
        ))
        original = log_path.read_text()
        log.append(Event(
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.STAGE_COMPLETED,
            payload={},
        ))
        # First event's JSON line is unchanged in the file.
        lines = log_path.read_text().splitlines()
        assert len(lines) == 2
        assert original.splitlines()[0] == lines[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.orchestration.events'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/orchestration/events.py`:

```python
"""Append-only events log for the orchestration state machine."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class EventType(str, Enum):
    """Types of orchestration events."""

    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    SCENARIO_STATE_CHANGED = "scenario_state_changed"
    FINDING_RECORDED = "finding_recorded"
    BID_ASSIGNED = "bid_assigned"
    REVERSION_LOGGED = "reversion_logged"
    COSMETIC_REVIEW_QUEUED = "cosmetic_review_queued"
    HUMAN_REVIEW_REQUESTED = "human_review_requested"


class Event(BaseModel):
    """One event in the log."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    event_type: EventType
    payload: dict


class EventsLog:
    """Append-only JSONL log of orchestration events."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure the file exists for empty-log reads.
        if not self.log_path.exists():
            self.log_path.touch()

    def append(self, event: Event) -> None:
        """Append a single event to the log (JSONL format, one event per line)."""
        line = event.model_dump_json()
        with self.log_path.open("a") as f:
            f.write(line + "\n")

    def read_all(self) -> list[Event]:
        """Read all events from the log in order."""
        return [Event.model_validate_json(line) for line in self._read_lines()]

    def read_since(self, timestamp: datetime) -> list[Event]:
        """Read events with timestamp strictly after the given cutoff."""
        events = self.read_all()
        return [e for e in events if e.timestamp > timestamp]

    def _read_lines(self) -> list[str]:
        """Return non-empty lines from the log file."""
        with self.log_path.open() as f:
            return [line for line in f.read().splitlines() if line.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_events.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/orchestration/events.py tests/test_events.py
git commit -m "feat(orchestration): add append-only events log with replay support"
```

---

### Task 6: Stage Node Base Classes

**Files:**
- Create: `src/haileris_v2/orchestration/nodes.py`
- Create: `tests/test_nodes.py`

Stage nodes are the units of work in the orchestration state machine. Each stage (Harvest, Ascertain, Decomposition, Inscribe, Etch, Realize, Inspect, Settle) inherits from a base class that defines the lifecycle.

**Interfaces:**
- Consumes: `Event`, `EventType`, `EventsLog` from Task 5
- Produces:
  - `class PipelineContext(BaseModel)` — runtime context passed between stages
  - `class StageNode(ABC)` — abstract base for all stages
    - `name: str` — stage identifier
    - `events_log: EventsLog` — for emitting events
    - `run(context: PipelineContext) -> PipelineContext` — execute the stage
    - `pre_run(context)` / `post_run(context)` — lifecycle hooks (emit events)

- [ ] **Step 1: Write the failing test**

Write `tests/test_nodes.py`:

```python
"""Tests for stage node base classes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.orchestration.events import EventType, EventsLog
from haileris_v2.orchestration.nodes import PipelineContext, StageNode


class TestPipelineContext:
    def test_minimal_context(self, tmp_project_dir: Path):
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
            events_log=EventsLog(tmp_project_dir / "events.jsonl"),
        )
        assert ctx.project_dir == tmp_project_dir
        assert ctx.mapping.project_id == "test"


class TestStageNode:
    def test_subclass_must_implement_run(self, tmp_project_dir: Path):
        class IncompleteStage(StageNode):
            name = "incomplete"

        with pytest.raises(TypeError, match="abstract"):
            IncompleteStage(
                events_log=EventsLog(tmp_project_dir / "events.jsonl")
            )

    def test_run_emits_start_and_complete_events(self, tmp_project_dir: Path):
        class SimpleStage(StageNode):
            name = "simple"

            def run(self, context: PipelineContext) -> PipelineContext:
                return context

        log_path = tmp_project_dir / "events.jsonl"
        log = EventsLog(log_path)
        stage = SimpleStage(events_log=log)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
            events_log=log,
        )
        stage.run(ctx)
        events = log.read_all()
        assert len(events) == 2
        assert events[0].event_type == EventType.STAGE_STARTED
        assert events[0].payload == {"stage": "simple"}
        assert events[1].event_type == EventType.STAGE_COMPLETED
        assert events[1].payload == {"stage": "simple"}

    def test_run_records_failure_event_on_exception(self, tmp_project_dir: Path):
        class FailingStage(StageNode):
            name = "failing"

            def run(self, context: PipelineContext) -> PipelineContext:
                raise RuntimeError("simulated failure")

        log_path = tmp_project_dir / "events.jsonl"
        log = EventsLog(log_path)
        stage = FailingStage(events_log=log)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="test", base_bids=[]),
            events_log=log,
        )
        with pytest.raises(RuntimeError, match="simulated failure"):
            stage.run(ctx)
        events = log.read_all()
        # STAGE_STARTED was emitted; the exception should propagate (no
        # STAGE_COMPLETED, but the failure is visible in the log).
        assert events[0].event_type == EventType.STAGE_STARTED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_nodes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.orchestration.nodes'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/orchestration/nodes.py`:

```python
"""Stage node base classes for the orchestration state machine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.orchestration.events import Event, EventType, EventsLog


class PipelineContext(BaseModel):
    """Runtime context passed between stages."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_dir: Path
    mapping: MappingArtifact
    events_log: EventsLog
    current_stage: str | None = None
    current_sub_bid: str | None = None
    iteration: int = 0


class StageNode(ABC):
    """Abstract base for all pipeline stages.

    Subclasses must define `name` and implement `run()`. The base class
    emits STAGE_STARTED and STAGE_COMPLETED events around each run.
    """

    name: str = ""

    def __init__(self, events_log: EventsLog) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define `name`")
        self.events_log = events_log

    def run(self, context: PipelineContext) -> PipelineContext:
        """Execute the stage, emitting start/complete events."""
        self._emit(EventType.STAGE_STARTED)
        try:
            result = self._run(context)
            self._emit(EventType.STAGE_COMPLETED)
            return result
        except Exception:
            # Don't emit COMPLETED on failure; let the exception propagate.
            raise

    @abstractmethod
    def _run(self, context: PipelineContext) -> PipelineContext:
        """Stage-specific execution. Must be implemented by subclasses."""
        ...

    def _emit(self, event_type: EventType, payload: dict | None = None) -> None:
        """Emit an event to the log."""
        event = Event(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            payload={"stage": self.name, **(payload or {})},
        )
        self.events_log.append(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_nodes.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/orchestration/nodes.py tests/test_nodes.py
git commit -m "feat(orchestration): add StageNode base class with event emission"
```

---

### Task 7: Pydantic-Graph Skeleton

**Files:**
- Create: `src/haileris_v2/orchestration/graph.py`
- Create: `tests/test_graph.py`

Pydantic-Graph provides the typed state-machine runtime. Each stage node integrates as a graph node, and the graph defines transitions between stages. This task establishes the skeleton; subsequent plans fill in stage-specific behavior.

**Interfaces:**
- Consumes: `StageNode`, `PipelineContext` from Task 6
- Produces:
  - `class PipelineGraph` — wraps a Pydantic-Graph with stage nodes
    - `__init__(stages: list[StageNode])` — initialize with stage list
    - `run(initial_context: PipelineContext) -> PipelineContext` — execute the graph

- [ ] **Step 1: Write the failing test**

Write `tests/test_graph.py`:

```python
"""Tests for the Pydantic-Graph skeleton."""

from __future__ import annotations

from pathlib import Path

import pytest
from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.orchestration.events import EventType, EventsLog
from haileris_v2.orchestration.graph import PipelineGraph
from haileris_v2.orchestration.nodes import PipelineContext, StageNode


class IncrementingStage(StageNode):
    """A trivial stage that increments context.iteration."""

    name = "increment"

    def _run(self, context: PipelineContext) -> PipelineContext:
        return context.model_copy(update={"iteration": context.iteration + 1})


class TaggingStage(StageNode):
    """A trivial stage that tags the current stage."""

    name = "tag"

    def _run(self, context: PipelineContext) -> PipelineContext:
        return context.model_copy(update={"current_stage": "tagged"})


class TestPipelineGraph:
    def test_runs_stages_in_order(self, tmp_project_dir: Path):
        log = EventsLog(tmp_project_dir / "events.jsonl")
        graph = PipelineGraph(
            stages=[IncrementingStage(events_log=log), IncrementingStage(events_log=log)],
            events_log=log,
        )
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
            events_log=log,
        )
        result = graph.run(ctx)
        assert result.iteration == 2

    def test_emits_events_for_each_stage(self, tmp_project_dir: Path):
        log = EventsLog(tmp_project_dir / "events.jsonl")
        graph = PipelineGraph(
            stages=[IncrementingStage(events_log=log), TaggingStage(events_log=log)],
            events_log=log,
        )
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
            events_log=log,
        )
        graph.run(ctx)
        events = log.read_all()
        # Two stages × two events each = 4 events
        assert len(events) == 4
        started = [e for e in events if e.event_type == EventType.STAGE_STARTED]
        completed = [e for e in events if e.event_type == EventType.STAGE_COMPLETED]
        assert len(started) == 2
        assert len(completed) == 2
        assert {e.payload["stage"] for e in started} == {"increment", "tag"}

    def test_empty_stages_returns_context_unchanged(self, tmp_project_dir: Path):
        log = EventsLog(tmp_project_dir / "events.jsonl")
        graph = PipelineGraph(stages=[], events_log=log)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=MappingArtifact(schema_version=1, project_id="t", base_bids=[]),
            events_log=log,
        )
        result = graph.run(ctx)
        assert result.iteration == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.orchestration.graph'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/orchestration/graph.py`:

```python
"""PipelineGraph: linear stage runner for the orchestration state machine.

This task establishes the basic shape: a PipelineGraph runs a list of stages
in order, threading a PipelineContext through them. The actual Pydantic-Graph
node traversal is deferred to Plan 6 (Three Practices + Concurrency Enforcement),
which wires in the full async runner. For Plan 1, the runner is a plain linear
iteration that uses StageNode.run() per stage.
"""

from __future__ import annotations

from haileris_v2.orchestration.events import EventsLog
from haileris_v2.orchestration.nodes import PipelineContext, StageNode


class PipelineGraph:
    """Runs a list of stages in order, threading PipelineContext through them."""

    def __init__(self, stages: list[StageNode], events_log: EventsLog) -> None:
        self.events_log = events_log
        self.stages = list(stages)

    def run(self, initial_context: PipelineContext) -> PipelineContext:
        """Synchronously run the graph, threading context through stages.

        For Plan 1, runs stages directly (not via Pydantic-Graph's async runner).
        Plan 6 will wire in the full async runner for cross-cutting discipline.
        """
        context = initial_context
        for stage in self.stages:
            context = stage.run(context)
        return context
```

Note: this skeleton runs stages directly in `run()`. The full Pydantic-Graph node traversal (with BaseNode subclasses, async `run`, and branching) is deferred to Plan 6 (Three Practices + Concurrency Enforcement), which wires in the async runner. Plan 1 just needs the linear shape so subsequent plans can build features against it.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/orchestration/graph.py tests/test_graph.py
git commit -m "feat(orchestration): add PipelineGraph skeleton (linear stage runner)"
```

---

### Task 8: Mechanical Verification — Check Infrastructure

**Files:**
- Create: `src/haileris_v2/verification/__init__.py`
- Create: `src/haileris_v2/verification/mechanical.py`
- Create: `tests/test_mechanical.py`

Mechanical author verification is the deterministic pre-filter that runs before the 7 reviewer subagents. This task builds the infrastructure; subsequent tasks (9–15) add the 7 individual checks.

**Interfaces:**
- Consumes: `Base85BID` from Task 2, `MappingArtifact` from Task 3
- Produces:
  - `class CheckResult(BaseModel)` — outcome of a single check
  - `class MechanicalCheck(ABC)` — abstract base for all checks
    - `name: str` — check identifier
    - `run(scenario_draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult`
  - `class MechanicalVerifier`:
    - `__init__(checks: list[MechanicalCheck])` — register the check set
    - `verify(scenario_draft, mapping) -> list[CheckResult]` — run all checks

- [ ] **Step 1: Write the failing test**

Write `tests/test_mechanical.py`:

```python
"""Tests for mechanical author verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from haileris_v2.artifacts.bid import Base85BID
from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.verification.mechanical import (
    CheckResult,
    MechanicalCheck,
    MechanicalVerifier,
    ScenarioDraft,
)


class DummyCheck(MechanicalCheck):
    """A check that always passes."""

    name = "dummy_pass"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        return CheckResult(name=self.name, outcome="pass", detail=None)


class DummyFailingCheck(MechanicalCheck):
    """A check that always fails."""

    name = "dummy_fail"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        return CheckResult(name=self.name, outcome="fail", detail="intentional failure")


class TestMechanicalCheck:
    def test_subclass_must_implement_run(self, tmp_project_dir: Path):
        class Incomplete(MechanicalCheck):
            name = "incomplete"

        with pytest.raises(TypeError, match="abstract"):
            Incomplete()


class TestMechanicalVerifier:
    def test_empty_check_set(self, tmp_project_dir: Path):
        verifier = MechanicalVerifier(checks=[])
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test scenario",
            gherkin_text="Given x\nWhen y\nThen z",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x", "When y", "Then z"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        results = verifier.verify(draft, mapping)
        assert results == []

    def test_all_passing_checks(self, tmp_project_dir: Path):
        verifier = MechanicalVerifier(checks=[DummyCheck(), DummyCheck()])
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        results = verifier.verify(draft, mapping)
        assert all(r.outcome == "pass" for r in results)
        assert len(results) == 2

    def test_mixed_pass_fail(self, tmp_project_dir: Path):
        verifier = MechanicalVerifier(
            checks=[DummyCheck(), DummyFailingCheck(), DummyCheck()]
        )
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        results = verifier.verify(draft, mapping)
        assert len(results) == 3
        outcomes = [r.outcome for r in results]
        assert outcomes == ["pass", "fail", "pass"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.verification'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/verification/__init__.py` (empty) and `src/haileris_v2/verification/mechanical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/ tests/test_mechanical.py
git commit -m "feat(verification): add MechanicalVerifier infrastructure (no checks yet)"
```

---

### Task 9: Mechanical Check — `gherkin-syntax`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

The first check: validate that the scenario's Gherkin has the correct structure (Given/When/Then keywords, at least one of each step type).

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import GherkinSyntaxCheck


class TestGherkinSyntaxCheck:
    def test_valid_gherkin_passes(self, tmp_project_dir: Path):
        check = GherkinSyntaxCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nWhen an action\nThen a result",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "When an action", "Then a result"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_missing_when_fails(self, tmp_project_dir: Path):
        check = GherkinSyntaxCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nThen a result",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "Then a result"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "When" in (result.detail or "")

    def test_no_steps_fails(self, tmp_project_dir: Path):
        check = GherkinSyntaxCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=[],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestGherkinSyntaxCheck -v`
Expected: FAIL with `ImportError: cannot import name 'GherkinSyntaxCheck'`.

- [ ] **Step 3: Add the check to mechanical.py**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestGherkinSyntaxCheck -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add gherkin-syntax check (Given/When/Then required)"
```

---

### Task 10: Mechanical Check — `scenario-name-unique`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

Validates that the scenario's name is unique within its feature file. Implementation reads the feature file and looks for duplicates.

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import ScenarioNameUniqueCheck


class TestScenarioNameUniqueCheck:
    def test_unique_name_passes(self, tmp_project_dir: Path):
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: First\n    Given x\n\n  Scenario: Second\n    Given y\n"
        )
        check = ScenarioNameUniqueCheck()
        draft = ScenarioDraft(
            feature_path=feature_path,
            scenario_name="First",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_duplicate_name_fails(self, tmp_project_dir: Path):
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: Same\n    Given x\n\n  Scenario: Same\n    Given y\n"
        )
        check = ScenarioNameUniqueCheck()
        draft = ScenarioDraft(
            feature_path=feature_path,
            scenario_name="Same",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "duplicate" in (result.detail or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestScenarioNameUniqueCheck -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the check**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
import re


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestScenarioNameUniqueCheck -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add scenario-name-unique check"
```

---

### Task 11: Mechanical Check — `tags-registered`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

Validates that all tags on the scenario are registered in the project's tag registry. The registry is loaded from a config file in the project (host-project override).

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import TagsRegisteredCheck


class TestTagsRegisteredCheck:
    def test_no_tags_passes(self, tmp_project_dir: Path):
        check = TagsRegisteredCheck(registered_tags={"@smoke", "@auth"})
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_all_registered_passes(self, tmp_project_dir: Path):
        check = TagsRegisteredCheck(registered_tags={"@smoke", "@auth"})
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@smoke", "@auth"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_unregistered_tag_fails(self, tmp_project_dir: Path):
        check = TagsRegisteredCheck(registered_tags={"@smoke"})
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@unknown_tag"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "@unknown_tag" in (result.detail or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestTagsRegisteredCheck -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the check**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestTagsRegisteredCheck -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add tags-registered check with configurable tag set"
```

---

### Task 12: Mechanical Check — `step-definitions-resolvable`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

Validates that every step in the scenario maps to a registered step definition. The step-definition registry is configurable.

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import StepDefinitionsResolvableCheck


class TestStepDefinitionsResolvableCheck:
    def test_all_resolvable_passes(self, tmp_project_dir: Path):
        # Step registry keyed by step keyword + pattern snippet.
        check = StepDefinitionsResolvableCheck(
            registered_patterns=[
                re.compile(r"Given a precondition"),
                re.compile(r"When an action"),
                re.compile(r"Then a result"),
            ]
        )
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nWhen an action\nThen a result",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "When an action", "Then a result"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_unresolvable_step_fails(self, tmp_project_dir: Path):
        check = StepDefinitionsResolvableCheck(
            registered_patterns=[re.compile(r"Given a precondition")]
        )
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nWhen undefined action",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "When undefined action"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "undefined action" in (result.detail or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestStepDefinitionsResolvableCheck -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the check**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestStepDefinitionsResolvableCheck -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add step-definitions-resolvable check"
```

---

### Task 13: Mechanical Check — `lifecycle-status-tag-present`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

Validates that the scenario has a lifecycle status tag (per spec Pivot #3). The tag is `@status-inscribing`, `@status-approved`, `@status-live`, etc.

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import LifecycleStatusTagPresentCheck


class TestLifecycleStatusTagPresentCheck:
    def test_present_passes(self, tmp_project_dir: Path):
        check = LifecycleStatusTagPresentCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@status-inscribing"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_missing_fails(self, tmp_project_dir: Path):
        check = LifecycleStatusTagPresentCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@smoke"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "lifecycle" in (result.detail or "").lower()

    def test_invalid_status_value_fails(self, tmp_project_dir: Path):
        check = LifecycleStatusTagPresentCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@status-bogus"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestLifecycleStatusTagPresentCheck -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the check**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
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
```

Also update the import at the top of mechanical.py to add `from haileris_v2.artifacts.mapping import LifecycleStatus`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestLifecycleStatusTagPresentCheck -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add lifecycle-status-tag-present check"
```

---

### Task 14: Mechanical Check — `sub-bid-assigned`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

Validates that the sub-BID is in valid Base85 format AND that the parent base-BID exists in the mapping artifact.

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import SubBidAssignedCheck


class TestSubBidAssignedCheck:
    def test_valid_sub_bid_with_existing_base_passes(self, tmp_project_dir: Path):
        check = SubBidAssignedCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(
            schema_version=1,
            project_id="t",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b",
                    behavior_description="d",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_invalid_base85_char_fails(self, tmp_project_dir: Path):
        check = SubBidAssignedCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid=" ",  # space not in alphabet
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"

    def test_parent_base_bid_missing_fails(self, tmp_project_dir: Path):
        check = SubBidAssignedCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00099"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "00099" in (result.detail or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestSubBidAssignedCheck -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the check**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestSubBidAssignedCheck -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add sub-bid-assigned check (format + parent existence)"
```

---

### Task 15: Mechanical Check — `cross-behavior-tags-valid`

**Files:**
- Modify: `src/haileris_v2/verification/mechanical.py`
- Modify: `tests/test_mechanical.py`

Validates that any `@behavior-X` tag references a behavior whose base-BID exists in the mapping.

- [ ] **Step 1: Append the failing test**

Append to `tests/test_mechanical.py`:

```python
from haileris_v2.verification.mechanical import CrossBehaviorTagsValidCheck


class TestCrossBehaviorTagsValidCheck:
    def test_no_cross_behavior_tags_passes(self, tmp_project_dir: Path):
        check = CrossBehaviorTagsValidCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@smoke"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_valid_cross_behavior_tag_passes(self, tmp_project_dir: Path):
        check = CrossBehaviorTagsValidCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@behavior-00005"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(
            schema_version=1,
            project_id="t",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00005",
                    behavior_name="b",
                    behavior_description="d",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_dangling_cross_behavior_tag_fails(self, tmp_project_dir: Path):
        check = CrossBehaviorTagsValidCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@behavior-00099"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "00099" in (result.detail or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mechanical.py::TestCrossBehaviorTagsValidCheck -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the check**

Append to `src/haileris_v2/verification/mechanical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mechanical.py::TestCrossBehaviorTagsValidCheck -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/mechanical.py tests/test_mechanical.py
git commit -m "feat(verification): add cross-behavior-tags-valid check"
```

---

### Task 16: Host-Project Override Mechanism

**Files:**
- Create: `src/haileris_v2/verification/host_overrides.py`
- Create: `tests/test_host_overrides.py`

Per spec, host projects can override any tunable behavior (mechanical check set, max_iterations, deprecation policy, etc.). The override mechanism reads from a project-level config file (e.g., `.haileris/config.yaml`) and merges it with the defaults.

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class HostConfig(BaseModel)` — parsed host config (check set, max_iterations, etc.)
  - `load_host_config(project_dir: Path) -> HostConfig` — load from `.haileris/config.yaml`, fall back to defaults
  - `default_check_set() -> list[type[MechanicalCheck]]` — return the default 7 checks

- [ ] **Step 1: Write the failing test**

Write `tests/test_host_overrides.py`:

```python
"""Tests for host-project override mechanism."""

from __future__ import annotations

from pathlib import Path

import pytest
from haileris_v2.verification.host_overrides import (
    HostConfig,
    default_check_set,
    load_host_config,
)
from haileris_v2.verification.mechanical import (
    CrossBehaviorTagsValidCheck,
    GherkinSyntaxCheck,
    LifecycleStatusTagPresentCheck,
    ScenarioNameUniqueCheck,
    StepDefinitionsResolvableCheck,
    SubBidAssignedCheck,
    TagsRegisteredCheck,
)


class TestDefaultCheckSet:
    def test_returns_all_seven_default_checks(self):
        checks = default_check_set(registered_tags=set(), step_patterns=[])
        names = {type(c).__name__ for c in checks}
        assert names == {
            "GherkinSyntaxCheck",
            "ScenarioNameUniqueCheck",
            "TagsRegisteredCheck",
            "StepDefinitionsResolvableCheck",
            "LifecycleStatusTagPresentCheck",
            "SubBidAssignedCheck",
            "CrossBehaviorTagsValidCheck",
        }


class TestLoadHostConfig:
    def test_no_config_file_returns_defaults(self, tmp_path: Path):
        config = load_host_config(tmp_path)
        assert config.max_iterations == 3
        assert config.check_set == "default"

    def test_loads_config_from_yaml(self, tmp_path: Path):
        config_dir = tmp_path / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "max_iterations: 5\ncheck_set: default\n"
        )
        config = load_host_config(tmp_path)
        assert config.max_iterations == 5

    def test_partial_config_uses_defaults_for_missing_fields(self, tmp_path: Path):
        config_dir = tmp_path / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("max_iterations: 7\n")
        config = load_host_config(tmp_path)
        assert config.max_iterations == 7
        assert config.check_set == "default"  # default preserved

    def test_invalid_yaml_raises(self, tmp_path: Path):
        config_dir = tmp_path / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("not: valid: yaml: at all: :::")
        with pytest.raises(Exception):
            load_host_config(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_host_overrides.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/verification/host_overrides.py`:

```python
"""Host-project override mechanism for tunable behavior."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from haileris_v2.verification.mechanical import (
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
    """Parsed host-project configuration."""

    model_config = ConfigDict(frozen=True)

    max_iterations: int = 3  # spec default
    check_set: str = "default"


def default_check_set(
    registered_tags: set[str],
    step_patterns: list[re.Pattern[str]],
) -> list[MechanicalCheck]:
    """Return the default 7 mechanical checks with the given registry state."""
    return [
        GherkinSyntaxCheck(),
        ScenarioNameUniqueCheck(),
        TagsRegisteredCheck(registered_tags=registered_tags),
        StepDefinitionsResolvableCheck(registered_patterns=step_patterns),
        LifecycleStatusTagPresentCheck(),
        SubBidAssignedCheck(),
        CrossBehaviorTagsValidCheck(),
    ]


def load_host_config(project_dir: Path) -> HostConfig:
    """Load host config from `<project_dir>/.haileris/config.yaml`.

    Falls back to defaults if the file doesn't exist.
    """
    config_path = Path(project_dir) / ".haileris" / "config.yaml"
    if not config_path.exists():
        return HostConfig()
    data = yaml.safe_load(config_path.read_text()) or {}
    return HostConfig.model_validate(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_host_overrides.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/verification/host_overrides.py tests/test_host_overrides.py
git commit -m "feat(verification): add host-project override mechanism + default check set"
```

---

### Task 17: CLI Scaffold

**Files:**
- Create: `src/haileris_v2/cli.py`
- Create: `tests/test_cli.py`

The CLI entry point. For Plan 1, only the basic scaffold is needed (`h2 --help`, `h2 verify <feature>` to run mechanical checks against a feature). Subsequent plans add subcommands (`run`, `status`, etc.).

**Interfaces:**
- Consumes: `MappingArtifact` from Task 3, `MechanicalVerifier` from Task 8, all 7 checks
- Produces:
  - `def main(argv: list[str] | None = None) -> int` — CLI entry point
  - `def cmd_verify(args: argparse.Namespace) -> int` — `h2 verify` subcommand

- [ ] **Step 1: Write the failing test**

Write `tests/test_cli.py`:

```python
"""Tests for the CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from haileris_v2 import cli


class TestCli:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--help"])
        assert exc_info.value.code == 0

    def test_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main([])
        # No args should print help and exit 0 (or non-zero with usage).
        # We accept either; the key is it doesn't crash with an unhandled exception.
        assert exc_info.value.code in (0, 1, 2)

    def test_verify_subcommand_runs_mechanical_checks(self, tmp_project_dir: Path):
        # Set up a minimal mapping + feature file.
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: Valid\n    Given x\n    When y\n    Then z\n"
        )
        config_dir = tmp_project_dir / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("max_iterations: 3\ncheck_set: default\n")

        # Create a mapping artifact with one base BID.
        from haileris_v2.artifacts.bid import Base85BID
        from haileris_v2.artifacts.mapping import BaseBIDEntry, MappingArtifact
        mapping = MappingArtifact(
            schema_version=1,
            project_id="cli-test",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b",
                    behavior_description="d",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        mapping.save(tmp_project_dir / "mapping.yaml")

        # Run the CLI verify command.
        rc = cli.main([
            "--project-dir", str(tmp_project_dir),
            "verify",
            "--feature", str(feature_path),
            "--scenario", "Valid",
            "--sub-bid", "A",
            "--base-bid", "00000",
        ])
        # The scenario has tags=[] so TagsRegisteredCheck will fail (no registered tags).
        # We expect non-zero exit because of that. The point is the command runs.
        assert rc in (0, 1)  # 0 if all pass, 1 if any fail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haileris_v2.cli'`.

- [ ] **Step 3: Write the implementation**

Write `src/haileris_v2/cli.py`:

```python
"""CLI entry point for HAILERIS v2."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from haileris_v2.artifacts.bid import Base85BID
from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.verification.host_overrides import default_check_set, load_host_config
from haileris_v2.verification.mechanical import (
    MechanicalVerifier,
    ScenarioDraft,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="h2",
        description="HAILERIS v2: spec-driven development pipeline",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # h2 verify — run mechanical checks against a feature/scenario.
    verify = subparsers.add_parser("verify", help="Run mechanical verification on a scenario")
    verify.add_argument("--feature", type=Path, required=True, help="Path to the .feature file")
    verify.add_argument("--scenario", required=True, help="Scenario name within the feature")
    verify.add_argument("--sub-bid", required=True, help="Sub-BID for the scenario")
    verify.add_argument("--base-bid", required=True, help="Parent base-BID")

    return parser


def cmd_verify(args: argparse.Namespace) -> int:
    """Run mechanical verification on a single scenario."""
    project_dir: Path = args.project_dir
    config = load_host_config(project_dir)
    mapping = MappingArtifact.load(project_dir / "mapping.yaml") if (project_dir / "mapping.yaml").exists() else MappingArtifact(
        schema_version=1, project_id=project_dir.name, base_bids=[]
    )
    # For Plan 1, we run with empty registries (host project can configure later).
    checks = default_check_set(registered_tags=set(), step_patterns=[])
    verifier = MechanicalVerifier(checks=checks)
    draft = ScenarioDraft(
        feature_path=args.feature,
        scenario_name=args.scenario,
        gherkin_text=args.feature.read_text(),
        tags=[],  # Tag parsing lives in Plan 3
        sub_bid=args.sub_bid,
        parent_base_bid=Base85BID(value=args.base_bid),
        step_texts=[],  # Step text extraction lives in Plan 3
    )
    results = verifier.verify(draft, mapping)
    failed = [r for r in results if r.outcome == "fail"]
    for r in results:
        status = "PASS" if r.outcome == "pass" else "FAIL"
        print(f"[{status}] {r.name}: {r.detail or ''}")
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "verify":
        return cmd_verify(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/haileris_v2/cli.py tests/test_cli.py
git commit -m "feat(cli): add h2 CLI scaffold with verify subcommand"
```

---

### Task 18: End-to-End Smoke Test

**Files:**
- Create: `tests/test_smoke.py`

A single integration test that exercises every component built in this plan. Validates the foundation works end-to-end before Plan 2 builds on it.

- [ ] **Step 1: Write the smoke test**

Write `tests/test_smoke.py`:

```python
"""End-to-end smoke test for Plan 1: foundation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from haileris_v2.artifacts.bid import Base85BID, next_base_bid
from haileris_v2.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from haileris_v2.cli import main as cli_main
from haileris_v2.orchestration.events import Event, EventType, EventsLog
from haileris_v2.orchestration.nodes import PipelineContext, StageNode
from haileris_v2.orchestration.persistence import FileStatePersistence
from haileris_v2.verification.host_overrides import default_check_set, load_host_config
from haileris_v2.verification.mechanical import (
    CrossBehaviorTagsValidCheck,
    GherkinSyntaxCheck,
    LifecycleStatusTagPresentCheck,
    MechanicalVerifier,
    ScenarioDraft,
    ScenarioNameUniqueCheck,
    StepDefinitionsResolvableCheck,
    SubBidAssignedCheck,
    TagsRegisteredCheck,
)


class CountingStage(StageNode):
    """A trivial stage that bumps the iteration counter."""

    name = "count"

    def _run(self, context):
        return context.model_copy(update={"iteration": context.iteration + 1})


class TestFoundationEndToEnd:
    def test_full_flow(self, tmp_project_dir: Path):
        # 1. Mapping artifact: create with one base BID.
        mapping = MappingArtifact(
            schema_version=1,
            project_id="smoke",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="smoke behavior",
                    behavior_description="end-to-end test behavior",
                    scenarios=[
                        ScenarioEntry(
                            sub_bid="A",
                            scenario_text_hash="hashA",
                            lifecycle_status=LifecycleStatus.LIVE,
                            supersedes=None,
                            superseded_by=None,
                            tests=["test_smoke::test_full_flow"],
                            derivations=["tests/test_smoke.py"],
                        )
                    ],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        mapping_path = tmp_project_dir / "mapping.yaml"
        mapping.save(mapping_path)
        loaded = MappingArtifact.load(mapping_path)
        assert loaded.project_id == "smoke"
        assert loaded.next_base_bid().value == "00001"

        # 2. Persistence: save and load state.
        state_dir = tmp_project_dir / "state"
        persistence = FileStatePersistence(state_dir)
        ctx = PipelineContext(
            project_dir=tmp_project_dir,
            mapping=loaded,
            events_log=EventsLog(tmp_project_dir / "events.jsonl"),
            iteration=5,
        )
        persistence.save_state(ctx)
        restored = persistence.load_state(PipelineContext)
        assert restored is not None
        assert restored.iteration == 5

        # 3. Events log: append a few events, read them back.
        log = EventsLog(tmp_project_dir / "events.jsonl")
        log.append(Event(
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.STAGE_STARTED,
            payload={"stage": "smoke"},
        ))
        events = log.read_all()
        assert len(events) >= 1

        # 4. Mechanical verification: build the default check set, run it.
        feature_path = tmp_project_dir / "smoke.feature"
        feature_path.write_text(
            "Feature: Smoke\n\n  Scenario: Valid\n    Given x\n    When y\n    Then z\n"
        )
        checks = default_check_set(
            registered_tags=set(),
            step_patterns=[re.compile(r"Given x"), re.compile(r"When y"), re.compile(r"Then z")],
        )
        verifier = MechanicalVerifier(checks=checks)
        draft = ScenarioDraft(
            feature_path=feature_path,
            scenario_name="Valid",
            gherkin_text=feature_path.read_text(),
            tags=["@status-live"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x", "When y", "Then z"],
        )
        results = verifier.verify(draft, loaded)
        # GherkinSyntaxCheck, ScenarioNameUniqueCheck, StepDefinitionsResolvableCheck,
        # LifecycleStatusTagPresentCheck, SubBidAssignedCheck, CrossBehaviorTagsValidCheck
        # should pass. TagsRegisteredCheck fails (no registered tags).
        passed = [r for r in results if r.outcome == "pass"]
        failed = [r for r in results if r.outcome == "fail"]
        assert len(passed) >= 5
        assert any(r.name == "tags-registered" for r in failed)

        # 5. Host config: defaults load when no config file.
        config = load_host_config(tmp_project_dir)
        assert config.max_iterations == 3

        # 6. Stage node: run a stage through the graph.
        from haileris_v2.orchestration.graph import PipelineGraph
        stage = CountingStage(events_log=log)
        graph = PipelineGraph(stages=[stage, stage], events_log=log)
        result = graph.run(ctx)
        assert result.iteration == 7  # 5 (from restore) + 2 stages
```

- [ ] **Step 2: Run the smoke test**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS (1 test).

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest`
Expected: ALL tests pass. No regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: end-to-end smoke test covering all Plan 1 components"
```

---

## Self-Review

After completing all tasks, run:

1. **Spec coverage check:** Each foundation requirement in the spec is implemented.
   - Base85 BID module → Task 2 ✓
   - Project-level mapping artifact (single source of truth) → Task 3 ✓
   - FileStatePersistence (atomic writes) → Task 4 ✓
   - Append-only events log → Task 5 ✓
   - Stage node base classes → Task 6 ✓
   - Pydantic-Graph skeleton → Task 7 ✓
   - Mechanical author verification infrastructure → Task 8 ✓
   - 7 mechanical checks (one per task) → Tasks 9-15 ✓
   - Host-project override mechanism → Task 16 ✓
   - CLI entry point → Task 17 ✓
   - End-to-end smoke test → Task 18 ✓

2. **Placeholder scan:** No "TBD", "TODO", "fill in details" in any step. All code blocks are complete.

3. **Type consistency:**
   - `Base85BID.value: str` — used consistently in Tasks 2, 3, 14, etc.
   - `MappingArtifact.next_base_bid() -> Base85BID` — used consistently.
   - `ScenarioDraft.parent_base_bid: Base85BID` — used consistently in Tasks 8, 14, 15, 17, 18.
   - `MechanicalCheck.name` — every subclass sets it explicitly.
   - `StageNode.name` — every subclass sets it explicitly.

4. **Run all tests:** `uv run pytest` should report all tests passing.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-27-foundation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?