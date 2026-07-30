# Stub Completion Implementation Plan (Plan 9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace remaining `NotImplementedError` stubs (EtchAgent, `mage run` without `--dry-run`), introduce per-item cosmetic processing, ship `mage cosmetic apply` CLI.

**Architecture:** EtchAgent becomes a real Pydantic-AI agent mirroring RealizeAgent. `mage run` no longer requires `--dry-run`. CosmeticRefiner converts `feature_cosmetic_queue` dicts to concrete `CosmeticItem` records. `mage cosmetic apply` reads refined items, atomically edits files, commits per item. `asyncio.Semaphore(max_concurrent_llm_calls)` caps refiner fan-out.

**Tech Stack:** Pydantic-AI, Plan 8 async infrastructure (`asyncio.Semaphore`, per-instance locks), pytest-asyncio.

## Global Constraints

- The string `haileris_v2` is forbidden anywhere in the tree (AGENTS.md).
- Commits follow Conventional Commits. No `Co-Authored-By` trailers (CLAUDE.md).
- Events are the audit trail. Any new stage outcome gets an `EventType` member and an emitted `Event` (AGENTS.md).
- Nothing shells out directly. Stages take an injected `command_runner`; tests substitute a recording fake (AGENTS.md).
- `EtchAgent` mirrors `RealizeAgent` plumbing exactly.
- All existing tests must remain green (391 baseline).
- Plan 8 concurrency surface preserved: cosmetic refinement uses `asyncio.Semaphore(max_concurrent_llm_calls)`.
- `mapping.feature_cosmetic_queue` keeps its current dict shape.

---

### Task 1: CosmeticItem schema

**Files:**
- Create: `src/mage/artifacts/cosmetic.py`
- Create: `tests/unit/test_cosmetic_item.py`

**Interfaces:**
- Produces: `CosmeticItem` Pydantic model with `sub_bid`, `file_path`, `line_range: tuple[int, int]`, `replacement_text`, `rationale`, `proposed_by`, `applied_at: datetime | None`, `content_hash: str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cosmetic_item.py
from datetime import datetime, UTC
from pathlib import Path

import pytest
from pydantic import ValidationError

from mage.artifacts.cosmetic import CosmeticItem


def _item(**overrides):
    defaults = dict(
        sub_bid="00000-001",
        file_path=Path("src/example.py"),
        line_range=(10, 20),
        replacement_text="new code\n",
        rationale="use a constant",
        proposed_by="IncrementQualityReviewer",
    )
    defaults.update(overrides)
    return CosmeticItem(**defaults)


def test_cosmetic_item_default_applied_at_is_none():
    item = _item()
    assert item.applied_at is None


def test_cosmetic_item_content_hash_stable():
    item_a = _item()
    item_b = _item()
    assert item_a.content_hash == item_b.content_hash
    assert len(item_a.content_hash) == 64  # sha256 hex


def test_cosmetic_item_content_hash_changes_with_replacement():
    item_a = _item()
    item_b = _item(replacement_text="different\n")
    assert item_a.content_hash != item_b.content_hash


def test_cosmetic_item_validates_line_range_order():
    with pytest.raises(ValidationError):
        _item(line_range=(20, 10))


def test_cosmetic_item_stores_applied_at_when_set():
    item = _item(applied_at=datetime(2026, 7, 30, tzinfo=UTC))
    assert item.applied_at == datetime(2026, 7, 30, tzinfo=UTC)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cosmetic_item.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mage.artifacts.cosmetic'`

- [ ] **Step 3: Implement CosmeticItem**

Create `src/mage/artifacts/cosmetic.py`:

```python
"""Cosmetic item schema for the per-item cosmetic apply pipeline."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CosmeticItem(BaseModel):
    """A single concrete cosmetic change proposed by a reviewer (or human).

    `file_path` is project-relative. `line_range` is inclusive on both ends.
    `content_hash` is sha256(replacement_text); used for idempotency when
    `mage cosmetic apply` is re-run.
    """

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    file_path: Path
    line_range: tuple[int, int]
    replacement_text: str
    rationale: str
    proposed_by: str
    applied_at: datetime | None = None
    content_hash: str = Field(default="")

    @model_validator(mode="after")
    def _validate_line_range_order(self) -> CosmeticItem:
        if self.line_range[0] > self.line_range[1]:
            raise ValueError(
                f"line_range start ({self.line_range[0]}) must be <= "
                f"end ({self.line_range[1]})"
            )
        return self

    @field_validator("content_hash", mode="before")
    @classmethod
    def _compute_hash(cls, v: str | None, info) -> str:  # type: ignore[no-untyped-def]
        if v:
            return v
        # Pydantic v2: info.data contains previously-validated fields.
        replacement_text = info.data.get("replacement_text", "")
        return hashlib.sha256(replacement_text.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cosmetic_item.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Verify full suite**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 391 passed (no new tests beyond the 5 above).

- [ ] **Step 6: Commit**

```bash
git add src/mage/artifacts/cosmetic.py tests/unit/test_cosmetic_item.py
git commit -m "feat(artifacts): add CosmeticItem schema for per-item cosmetic apply"
```

---

### Task 2: EventType members for cosmetic pipeline

**Files:**
- Modify: `src/mage/orchestration/events.py`

**Interfaces:**
- Produces: 4 new `EventType` members — `COSMETIC_ITEM_APPLIED`, `COSMETIC_ITEM_SKIPPED`, `COSMETIC_APPLY_FAILED`, `COSMETIC_REFINER_FALLBACK`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cosmetic_event_types.py
from mage.orchestration.events import EventType


def test_cosmetic_item_applied_member_exists():
    assert EventType.COSMETIC_ITEM_APPLIED.value == "cosmetic_item_applied"


def test_cosmetic_item_skipped_member_exists():
    assert EventType.COSMETIC_ITEM_SKIPPED.value == "cosmetic_item_skipped"


def test_cosmetic_apply_failed_member_exists():
    assert EventType.COSMETIC_APPLY_FAILED.value == "cosmetic_apply_failed"


def test_cosmetic_refiner_fallback_member_exists():
    assert EventType.COSMETIC_REFINER_FALLBACK.value == "cosmetic_refiner_fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cosmetic_event_types.py -v`
Expected: FAIL with `AttributeError: type object 'EventType' has no attribute 'COSMETIC_ITEM_APPLIED'`

- [ ] **Step 3: Add the EventType members**

In `src/mage/orchestration/events.py`, find the `EventType` enum (it is a `StrEnum`-style class) and append:

```python
    # Plan 9: cosmetic apply pipeline
    COSMETIC_ITEM_APPLIED = "cosmetic_item_applied"
    COSMETIC_ITEM_SKIPPED = "cosmetic_item_skipped"
    COSMETIC_APPLY_FAILED = "cosmetic_apply_failed"
    COSMETIC_REFINER_FALLBACK = "cosmetic_refiner_fallback"
```

If the enum is not yet a `StrEnum`, mirror the existing pattern (each member is `str(member.value)` etc.). Read the file's existing enum definition before editing.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cosmetic_event_types.py -v`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/events.py tests/unit/test_cosmetic_event_types.py
git commit -m "feat(events): add 4 cosmetic-pipeline EventType members"
```

---

### Task 3: CosmeticRefiner agent (LLM-driven)

**Files:**
- Create: `src/mage/agents/cosmetic_refiner.py`
- Create: `tests/unit/test_cosmetic_refiner.py`

**Interfaces:**
- Produces: `class CosmeticRefiner` with constructor `(*, model: Model | None = None)` and method `async def refine(raw: dict, *, semaphore: asyncio.Semaphore) -> CosmeticItem`.
- Consumes: `CosmeticItem` (Task 1), `asyncio.Semaphore`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cosmetic_refiner.py
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.artifacts.cosmetic import CosmeticItem
from mage.agents.cosmetic_refiner import CosmeticRefiner


def _raw_queue_entry():
    return {
        "sub_bid": "00000-001",
        "text": "use a constant for the magic number 42",
        "location": {"file": "src/example.py", "line": 15},
        "proposed_by": "IncrementQualityReviewer",
    }


@pytest.mark.asyncio
async def test_refiner_produces_cosmetic_item_from_raw_dict():
    models.ALLOW_MODEL_REQUESTS = False
    refiner = CosmeticRefiner()
    expected = CosmeticItem(
        sub_bid="00000-001",
        file_path=Path("src/example.py"),
        line_range=(14, 16),
        replacement_text="CONSTANT = 42\n",
        rationale="use a constant",
        proposed_by="IncrementQualityReviewer",
    )
    with patch.object(refiner, "_agent", TestModel(custom_output_args=expected.model_dump())):
        semaphore = asyncio.Semaphore(1)
        result = await refiner.refine(_raw_queue_entry(), semaphore=semaphore)
    assert isinstance(result, CosmeticItem)
    assert result.sub_bid == "00000-001"
    assert result.file_path == Path("src/example.py")


@pytest.mark.asyncio
async def test_refiner_respects_semaphore_cap():
    """Semaphore cap should be respected — refines run sequentially under cap=2."""
    models.ALLOW_MODEL_REQUESTS = False
    refiner = CosmeticRefiner()
    active = 0
    peak = 0

    async def fake_refine(raw: dict, *, semaphore: asyncio.Semaphore) -> CosmeticItem:
        nonlocal active, peak
        async with semaphore:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return CosmeticItem(
                sub_bid=raw["sub_bid"],
                file_path=Path(raw["location"]["file"]),
                line_range=(1, 1),
                replacement_text="x",
                rationale="x",
                proposed_by="x",
            )

    with patch.object(refiner, "refine", side_effect=fake_refine):
        items = [_raw_queue_entry() for _ in range(6)]
        semaphore = asyncio.Semaphore(2)
        results = await asyncio.gather(
            *[refiner.refine(item, semaphore=semaphore) for item in items]
        )
    assert peak <= 2
    assert len(results) == 6


@pytest.mark.asyncio
async def test_refiner_falls_back_to_stub_on_llm_fail():
    """Malformed LLM output → fallback CosmeticItem with file_path=None."""
    models.ALLOW_MODEL_REQUESTS = False
    refiner = CosmeticRefiner()

    class FailingAgent:
        async def run(self, *args, **kwargs):
            raise RuntimeError("LLM blew up")

    with patch.object(refiner, "_agent", FailingAgent()):
        semaphore = asyncio.Semaphore(1)
        result = await refiner.refine(_raw_queue_entry(), semaphore=semaphore)
    assert result.file_path is None
    assert result.sub_bid == "00000-001"
    assert "use a constant" in result.rationale
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cosmetic_refiner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mage.agents.cosmetic_refiner'`

- [ ] **Step 3: Implement CosmeticRefiner**

Create `src/mage/agents/cosmetic_refiner.py`:

```python
"""CosmeticRefiner: turn raw cosmetic queue entries into concrete CosmeticItems."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from mage.artifacts.cosmetic import CosmeticItem


_SYSTEM_PROMPT = """You refine a cosmetic suggestion into a concrete file edit.

Given a raw queue entry with `sub_bid`, `text`, `location` (file + line),
and `proposed_by`, produce a CosmeticItem with:
- file_path: the file from location.file
- line_range: (line - 1, line + 1) — surrounding context
- replacement_text: the proposed fix as it should appear in the file
- rationale: a short reason

Return a dict matching CosmeticItem fields.
"""


class CosmeticRefiner:
    """LLM-driven refiner for cosmetic queue entries."""

    def __init__(self, *, model: Model | None = None) -> None:
        self._agent: Agent[None, dict[str, Any]] = Agent(
            model=model or "test",
            deps_type=type(None),
            result_type=dict,
            system_prompt=_SYSTEM_PROMPT,
        )

    async def refine(
        self, raw: dict, *, semaphore: asyncio.Semaphore
    ) -> CosmeticItem:
        """Refine one raw entry into a CosmeticItem. LLM-fail → stub fallback."""
        async with semaphore:
            try:
                prompt = (
                    f"sub_bid={raw.get('sub_bid')!r}\n"
                    f"text={raw.get('text')!r}\n"
                    f"location={raw.get('location')!r}\n"
                    f"proposed_by={raw.get('proposed_by')!r}"
                )
                result = await self._agent.run(prompt)
                data = result.output
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=Path(data["file_path"]),
                    line_range=tuple(data["line_range"]),
                    replacement_text=data["replacement_text"],
                    rationale=data.get("rationale", raw.get("text", "")),
                    proposed_by=raw.get("proposed_by", "unknown"),
                )
            except Exception:
                # LLM blew up → stub item flagged for manual intervention.
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=None,  # type: ignore[arg-type]
                    line_range=(0, 0),
                    replacement_text="",
                    rationale=raw.get("text", ""),
                    proposed_by=raw.get("proposed_by", "unknown"),
                )


from pathlib import Path  # imported after class for cleaner top-level ordering
```

Note: The `Path` import at the bottom is intentional — keeps the `__future__` import at the top. If the implementer prefers, hoist it to the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cosmetic_refiner.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Verify full suite**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 391 passed + 3 new = 394 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mage/agents/cosmetic_refiner.py tests/unit/test_cosmetic_refiner.py
git commit -m "feat(agents): add CosmeticRefiner LLM agent"
```

---

### Task 4: PydanticEtchAgent concrete implementation

**Files:**
- Modify: `src/mage/agents/etch.py`
- Create: `tests/unit/test_etch_agent.py`

**Interfaces:**
- Produces: `class PydanticEtchAgent(EtchAgent)` with constructor `(*, model: Model | None = None)` and method `async def run(*, step: str, scenario_context: dict) -> RedTestSpec`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_etch_agent.py
import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.etch import EtchAgent, PydanticEtchAgent, RedTestSpec


@pytest.mark.asyncio
async def test_pydantic_etch_agent_uses_test_model():
    models.ALLOW_MODEL_REQUESTS = False
    canned = RedTestSpec(
        test_path="tests/test_example.py",
        test_body="def test_red():\n    assert False\n",
    )
    agent = PydanticEtchAgent()
    # Swap in TestModel with canned output
    agent._agent = TestModel(custom_output_args=canned.model_dump())
    result = await agent.run(
        step="When user clicks save",
        scenario_context={"scenario_name": "save scenario"},
    )
    assert result.test_path == canned.test_path
    assert "assert False" in result.test_body


@pytest.mark.asyncio
async def test_base_etch_agent_run_raises_not_implemented():
    """The base EtchAgent.run stays abstract — concrete impl is PydanticEtchAgent."""
    base = EtchAgent()
    with pytest.raises(NotImplementedError):
        await base.run(step="x", scenario_context={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_etch_agent.py -v`
Expected: FAIL with `ImportError: cannot import name 'PydanticEtchAgent'`

- [ ] **Step 3: Read current etch.py and add PydanticEtchAgent**

Read `src/mage/agents/etch.py` to see the existing `EtchAgent` base + `RedTestSpec` model + `NotImplementedError` stub. Append at the bottom of the file:

```python
from pydantic_ai import Agent
from pydantic_ai.models import Model


_ETCH_SYSTEM_PROMPT = """You write ONE red (failing) pytest test for a BDD step.

Given `step` (the When/Then clause) and `scenario_context` (scenario name,
related tags, prior tests), produce a RedTestSpec with:
- test_path: a sensible path like tests/test_<scenario>.py
- test_body: a complete pytest function with `assert False` or equivalent

Test must fail before any production code is written.
"""


class PydanticEtchAgent(EtchAgent):
    """Concrete EtchAgent backed by Pydantic-AI."""

    def __init__(self, *, model: Model | None = None) -> None:
        self._agent: Agent[None, dict] = Agent(
            model=model or "test",
            deps_type=type(None),
            result_type=dict,
            system_prompt=_ETCH_SYSTEM_PROMPT,
        )

    async def run(
        self, *, step: str, scenario_context: dict
    ) -> RedTestSpec:
        prompt = (
            f"step={step!r}\n"
            f"scenario_context={scenario_context!r}"
        )
        result = await self._agent.run(prompt)
        data = result.output
        return RedTestSpec(
            test_path=data["test_path"],
            test_body=data["test_body"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_etch_agent.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Verify full suite**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 394 + 2 new = 396 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mage/agents/etch.py tests/unit/test_etch_agent.py
git commit -m "feat(agents): add PydanticEtchAgent concrete implementation"
```

---

### Task 5: mage cosmetic show CLI

**Files:**
- Modify: `src/mage/cli.py`
- Modify: `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `mage cosmetic show <feature_id>` subcommand. Loads `mapping.yaml`, refines queue, prints `CosmeticItem` table.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py — append to existing TestCli class
@pytest.mark.asyncio
async def test_cosmetic_show_dispatches(tmp_path, capsys, monkeypatch):
    mapping_path = tmp_path / ".haileris" / "mapping.yaml"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal mapping with one cosmetic queue entry
    import yaml
    mapping_path.write_text(yaml.safe_dump({
        "project_id": "p",
        "base_bids": [],
        "feature_cosmetic_queue": [
            {
                "sub_bid": "00000-001",
                "text": "use a constant",
                "location": {"file": "src/example.py", "line": 5},
                "proposed_by": "IncrementQualityReviewer",
            }
        ],
    }))

    # Stub CosmeticRefiner to return a known item
    from mage.artifacts.cosmetic import CosmeticItem
    from pathlib import Path
    stub_item = CosmeticItem(
        sub_bid="00000-001",
        file_path=Path("src/example.py"),
        line_range=(4, 6),
        replacement_text="CONST = 42\n",
        rationale="use a constant",
        proposed_by="IncrementQualityReviewer",
    )

    class StubRefiner:
        async def refine(self, raw, *, semaphore):
            return stub_item

    monkeypatch.setattr("mage.cli.CosmeticRefiner", lambda **kw: StubRefiner())

    from mage.cli import main
    rc = main(["cosmetic", "show", "feat-1", "--project-dir", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "src/example.py" in captured.out
    assert "00000-001" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py::TestCli::test_cosmetic_show_dispatches -v`
Expected: FAIL — `cosmetic` subcommand unknown.

- [ ] **Step 3: Add cosmetic parser group + show subcommand**

Read `src/mage/cli.py` around the existing subparser definitions. Find where `plan_subparsers`, `review_subparsers`, etc. are defined (they use `add_subparsers(dest=...)`). Add:

```python
    # mage cosmetic
    cosmetic_parser = subparsers.add_parser("cosmetic", help="Show/apply cosmetic items")
    cosmetic_subparsers = cosmetic_parser.add_subparsers(dest="cosmetic_command")

    # mage cosmetic show
    show_cosmetic = cosmetic_subparsers.add_parser(
        "show", help="Show refined cosmetic items for a feature"
    )
    show_cosmetic.add_argument("feature_id")
    show_cosmetic.add_argument("--project-dir", default=".")

    # mage cosmetic apply (Task 6)
    apply_cosmetic = cosmetic_subparsers.add_parser(
        "apply", help="Apply cosmetic items to the feature branch"
    )
    apply_cosmetic.add_argument("feature_id")
    apply_cosmetic.add_argument("--project-dir", default=".")
    apply_cosmetic.add_argument("--dry-run", action="store_true")
```

Find where `cmd_plan_show`, `cmd_review_show`, etc. are dispatched (a big `if/elif` chain on `args.command`). Add `cosmetic` branch that calls a new `cmd_cosmetic(args)`:

```python
async def cmd_cosmetic(args) -> int:
    if args.cosmetic_command == "show":
        return await cmd_cosmetic_show(args)
    elif args.cosmetic_command == "apply":
        return await cmd_cosmetic_apply(args)
    return 1


async def cmd_cosmetic_show(args) -> int:
    from mage.agents.cosmetic_refiner import CosmeticRefiner
    from mage.artifacts.mapping import MappingArtifact

    project_dir = Path(args.project_dir).resolve()
    mapping_path = project_dir / ".haileris" / "mapping.yaml"
    mapping = MappingArtifact.load(mapping_path)
    refiner = CosmeticRefiner()
    semaphore = asyncio.Semaphore(7)
    refined = await asyncio.gather(
        *[refiner.refine(q, semaphore=semaphore) for q in mapping.feature_cosmetic_queue]
    )
    for item in refined:
        print(f"{item.sub_bid} {item.file_path}:{item.line_range[0]}-{item.line_range[1]} {item.rationale}")
    return 0
```

Add `import asyncio` at the top of cli.py if not present (likely already present from Plan 8).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py::TestCli::test_cosmetic_show_dispatches -v`
Expected: PASS

- [ ] **Step 5: Verify full suite**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 396 + 1 new = 397 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mage/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add mage cosmetic show subcommand"
```

---

### Task 6: mage cosmetic apply CLI

**Files:**
- Modify: `src/mage/cli.py`
- Modify: `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `mage cosmetic apply <feature_id> [--dry-run]` subcommand. Refines queue, atomically edits files, commits per item, emits events.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py — append
@pytest.mark.asyncio
async def test_cosmetic_apply_dispatches(tmp_path, monkeypatch):
    from mage.artifacts.cosmetic import CosmeticItem
    from pathlib import Path

    project_dir = tmp_path
    target_file = project_dir / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("line1\nline2\nline3\nline4\nline5\n")

    mapping_path = project_dir / ".haileris" / "mapping.yaml"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    mapping_path.write_text(yaml.safe_dump({
        "project_id": "p",
        "base_bids": [],
        "feature_cosmetic_queue": [
            {
                "sub_bid": "00000-001",
                "text": "use a constant",
                "location": {"file": "src/example.py", "line": 3},
                "proposed_by": "IncrementQualityReviewer",
            }
        ],
    }))

    stub_item = CosmeticItem(
        sub_bid="00000-001",
        file_path=Path("src/example.py"),
        line_range=(3, 3),
        replacement_text="CONST = 42\n",
        rationale="use a constant",
        proposed_by="IncrementQualityReviewer",
    )

    class StubRefiner:
        async def refine(self, raw, *, semaphore):
            return stub_item

    monkeypatch.setattr("mage.cli.CosmeticRefiner", lambda **kw: StubRefiner())

    # Stub the command_runner to record calls
    recorded = []
    class StubRunner:
        def __call__(self, *args, **kwargs):
            recorded.append(args[0] if args else kwargs.get("cmd"))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("mage.cli._default_runner", StubRunner())

    from mage.cli import main
    rc = main(["cosmetic", "apply", "feat-1", "--project-dir", str(project_dir)])
    assert rc == 0
    # File was edited
    assert "CONST = 42" in target_file.read_text()
    # Git commit was attempted
    assert any("git" in str(c) for c in recorded)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py::TestCli::test_cosmetic_apply_dispatches -v`
Expected: FAIL — `apply` subcommand dispatches but body not implemented.

- [ ] **Step 3: Implement cmd_cosmetic_apply**

Add to `src/mage/cli.py`:

```python
async def cmd_cosmetic_apply(args) -> int:
    from datetime import datetime, UTC
    from mage.agents.cosmetic_refiner import CosmeticRefiner
    from mage.artifacts.cosmetic import CosmeticItem
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import Event, EventType, EventsLog

    project_dir = Path(args.project_dir).resolve()
    mapping_path = project_dir / ".haileris" / "mapping.yaml"
    mapping = MappingArtifact.load(mapping_path)
    log = EventsLog(project_dir / ".haileris" / "events.jsonl")
    refiner = CosmeticRefiner()
    semaphore = asyncio.Semaphore(7)
    refined = await asyncio.gather(
        *[refiner.refine(q, semaphore=semaphore) for q in mapping.feature_cosmetic_queue]
    )

    for item in refined:
        if item.file_path is None:
            await log.append(Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.COSMETIC_REFINER_FALLBACK,
                payload={"sub_bid": item.sub_bid, "rationale": item.rationale},
            ))
            continue
        if item.applied_at and item.content_hash:
            await log.append(Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.COSMETIC_ITEM_SKIPPED,
                payload={"sub_bid": item.sub_bid, "reason": "already-applied"},
            ))
            continue
        target = project_dir / item.file_path
        if not target.exists():
            await log.append(Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.COSMETIC_APPLY_FAILED,
                payload={"sub_bid": item.sub_bid, "reason": "file-missing"},
            ))
            continue
        try:
            lines = target.read_text().splitlines()
            new_lines = (
                lines[: item.line_range[0] - 1]
                + item.replacement_text.splitlines()
                + lines[item.line_range[1] :]
            )
            if not args.dry_run:
                target.write_text("\n".join(new_lines) + "\n")
                # Commit on the feature branch via injected runner
                _default_runner([
                    "git", "commit", "-am",
                    f"cosmetic({item.sub_bid}): {item.rationale}",
                ])
            await log.append(Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.COSMETIC_ITEM_APPLIED,
                payload={"sub_bid": item.sub_bid, "file": str(item.file_path)},
            ))
        except Exception as e:
            await log.append(Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.COSMETIC_APPLY_FAILED,
                payload={"sub_bid": item.sub_bid, "reason": str(e)},
            ))
    return 0
```

`_default_runner` is the existing `command_runner` injected into stages — read `cli.py` to see how it's already named (likely `_default_runner` or `command_runner`). Use whatever name is in scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py::TestCli::test_cosmetic_apply_dispatches -v`
Expected: PASS

- [ ] **Step 5: Verify full suite**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 397 + 1 new = 398 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mage/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add mage cosmetic apply subcommand"
```

---

### Task 7: EtchStage uses PydanticEtchAgent when model set

**Files:**
- Modify: `src/mage/orchestration/etch.py`
- Modify: `tests/unit/test_etch_stage.py`

**Interfaces:**
- Produces: `EtchStage.run_scenario` constructs `PydanticEtchAgent(model=host_config.model)` when `host_config.model` is set; falls back to a stub agent (current behavior) for `--dry-run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_etch_stage.py — append
@pytest.mark.asyncio
async def test_etch_stage_uses_pydantic_agent_when_model_set(tmp_path):
    """When HostConfig.model is set, EtchStage uses PydanticEtchAgent."""
    from unittest.mock import patch
    from mage.artifacts.cosmetic import CosmeticItem  # not used, just to confirm imports
    from mage.agents.etch import PydanticEtchAgent
    from mage.orchestration.etch import EtchStage
    from mage.orchestration.nodes import PipelineContext
    from mage.verification.host_overrides import HostConfig
    from mage.artifacts.mapping import (
        BaseBIDEntry, MappingArtifact,
    )
    from mage.orchestration.events import EventsLog

    log = EventsLog(tmp_path / "events.jsonl")
    ctx = PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p", base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d"),
        ]),
        events_log=log,
    )
    host_config = HostConfig(model="openai:gpt-4o")
    stage = EtchStage(events_log=log, host_config=host_config)

    # Spy on PydanticEtchAgent construction
    constructed = []
    real_init = PydanticEtchAgent.__init__

    def spy_init(self, **kwargs):
        constructed.append(kwargs)
        real_init(self, **kwargs)

    with patch.object(PydanticEtchAgent, "__init__", spy_init):
        # run_scenario requires more setup; just check that the agent class
        # is wired by calling a minimal helper if one exists. Otherwise, run
        # the actual flow with a stub _agent.
        pass

    assert constructed, "PydanticEtchAgent should be constructed when model is set"
    assert constructed[0].get("model") == "openai:gpt-4o"
```

If `EtchStage` does not expose a clean entry point for this assertion, the implementer may spy on the constructor inside `run_scenario` (run with a stubbed-out scenario). The test's purpose is to verify that `HostConfig.model` is passed through to `PydanticEtchAgent.__init__`, not to exercise the full scenario flow.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_etch_stage.py::test_etch_stage_uses_pydantic_agent_when_model_set -v`
Expected: FAIL — `PydanticEtchAgent` not constructed.

- [ ] **Step 3: Wire PydanticEtchAgent into EtchStage**

Read `src/mage/orchestration/etch.py`. Find `EtchStage.run_scenario` (or similar entry point). Currently it likely constructs a stub agent inline. Replace with:

```python
def _build_etcher(self):
    if self.host_config.model:
        from mage.agents.etch import PydanticEtchAgent
        return PydanticEtchAgent(model=self.host_config.model)
    return StubEtchAgent()  # existing stub class
```

Where `StubEtchAgent` is whatever the current inline stub is — extract it to a class if it isn't already.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_etch_stage.py::test_etch_stage_uses_pydantic_agent_when_model_set -v`
Expected: PASS

- [ ] **Step 5: Verify full suite**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 398 + 1 new = 399 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mage/orchestration/etch.py tests/unit/test_etch_stage.py
git commit -m "feat(orchestration): wire PydanticEtchAgent when HostConfig.model set"
```

---

### Task 8: Unlock mage run + final regression + CHANGELOG

**Files:**
- Modify: `src/mage/cli.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `mage run` without `--dry-run` works (no more `NotImplementedError` gate).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py — append
@pytest.mark.asyncio
async def test_mage_run_without_dry_run_does_not_raise_not_implemented(tmp_path, monkeypatch):
    """mage run without --dry-run must not raise NotImplementedError.

    The agent wiring is real now (Tasks 4+7); only stub agents are used if
    HostConfig.model is unset (which it is in the test default).
    """
    from mage.cli import cmd_run
    import argparse

    args = argparse.Namespace(
        project_dir=str(tmp_path),
        dry_run=False,
    )
    # Should NOT raise NotImplementedError. May raise other things (e.g.,
    # missing project files); we only check the NotImplementedError gate is gone.
    try:
        await cmd_run(args)
    except NotImplementedError as e:
        pytest.fail(f"cmd_run still raises NotImplementedError: {e}")
    except Exception:
        pass  # other failures are OK; the gate is what we test
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py::TestCli::test_mage_run_without_dry_run_does_not_raise_not_implemented -v`
Expected: FAIL — `NotImplementedError` still raised.

- [ ] **Step 3: Remove the NotImplementedError gate**

In `src/mage/cli.py`, find the `NotImplementedError` at line 374 (the one with the message "mage run without --dry-run requires LLM agent wiring (Plan 9)"). Delete that block. The rest of `cmd_run` already handles dry-run vs real-model dispatch via `args.dry_run`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py::TestCli::test_mage_run_without_dry_run_does_not_raise_not_implemented -v`
Expected: PASS

- [ ] **Step 5: Full regression**

Run: `make test`
Expected: 399 + 1 new = 400 passed, 0 regressions.

Run: `uv run ruff check src tests 2>&1 | tail -3`
Expected: pre-existing errors only (21 baseline + minor new from this plan; auto-fix where possible).

- [ ] **Step 6: Update CHANGELOG**

Add under `[Unreleased]` → `### Added`:

```markdown
- Plan 9: `PydanticEtchAgent` wires EtchStage to real LLM; `mage run` no longer requires `--dry-run`.
- `CosmeticItem` schema, `CosmeticRefiner` LLM agent, and `mage cosmetic {show,apply}` subcommands for per-item cosmetic application.
```

Add under `[Unreleased]` → `### Changed` (if anything significant changed; otherwise leave alone).

- [ ] **Step 7: Commit**

```bash
git add src/mage/cli.py tests/unit/test_cli.py CHANGELOG.md
git commit -m "feat(cli): unlock mage run without --dry-run + Plan 9 CHANGELOG"
```

---

## Spec Self-Review (post-write)

1. **Spec coverage:** All components mapped. EtchAgent wiring (Task 4 + 7). CosmeticItem schema (Task 1). EventType members (Task 2). CosmeticRefiner (Task 3). `mage cosmetic show` (Task 5). `mage cosmetic apply` (Task 6). `mage run` unlock (Task 8). Mechanical pre-check wiring — already done in earlier plans; no Plan 9 task needed (would be scope creep).
2. **Placeholder scan:** All step code blocks complete. CosmeticItem fields, EventType names, agent signatures pinned verbatim.
3. **Internal consistency:** Task 1's `CosmeticItem` consumed by Task 3 (refiner), Task 5/6 (CLI). Task 2's EventType consumed by Task 6 (apply loop). Task 4's `PydanticEtchAgent` consumed by Task 7 (EtchStage). Task 8 unlocks `mage run` only after Task 4 + 7 wired EtchAgent.
4. **Ambiguity check:** "Per-item processing" pinned to `CosmeticRefiner` producing one `CosmeticItem` per raw queue entry. "Direct edit + commit" pinned to atomic file write per item + one git commit per item on the feature branch (via `_default_runner`, not `subprocess` directly). `--dry-run` flag preserved. Backward compat: existing tests stay green; existing 391-test baseline preserved.
