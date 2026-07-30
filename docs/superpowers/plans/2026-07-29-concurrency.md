# Concurrency — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add asyncio-based parallelism to LLM-bound and read-only operations while preserving sequential-per-scenario discipline (Plan 7 P2) and serialized writes to shared artifacts.

**Architecture:** `graph.run()` becomes an async coroutine. StageNodes gain async `_run` methods. `asyncio.gather` fires independent calls; `asyncio.Lock` per write target serializes only the contended regions. `PipelineContext.current_sub_bid` becomes thread-safe. `HostConfig.max_concurrent_llm_calls` knob (default 7) caps gather fan-out via `asyncio.Semaphore`.

**Tech Stack:** `asyncio` (stdlib), `pytest-asyncio` (test runner), existing Pydantic-Graph + Pydantic-AI (already async-capable).

## Global Constraints

- The string `haileris_v2` is forbidden anywhere in the tree (AGENTS.md).
- Commits follow Conventional Commits. No `Co-Authored-By` trailers (CLAUDE.md).
- Events are the audit trail (AGENTS.md).
- Nothing shells out directly. Stages take an injected `command_runner`; tests substitute a recording fake (AGENTS.md).
- Plan 7 P2 (sequential per-scenario cycles) is preserved verbatim.
- All existing tests must remain green (381 baseline).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/mage/orchestration/nodes.py` | Modify | `StageNode.run` becomes async wrapper around `_run` |
| `src/mage/orchestration/events.py` | Modify | `EventsLog.append` acquires `asyncio.Lock` |
| `src/mage/artifacts/mapping.py` | Modify | `MappingArtifact.save` acquires `asyncio.Lock` |
| `src/mage/orchestration/discipline/policy.py` | Modify | `acquire_cycle_lock`/`release_cycle_lock` become async |
| `src/mage/verification/host_overrides.py` | Modify | Add `max_concurrent_llm_calls: int = 7` |
| `src/mage/orchestration/graph.py` | Modify | `run()` becomes async coroutine |
| `src/mage/orchestration/inscribe.py` | Modify | `_run` async; reviewers via `asyncio.gather` with semaphore |
| `src/mage/orchestration/inspect_feature.py` | Modify | `_run` async; per-scenario Inspect via `asyncio.gather` |
| `src/mage/orchestration/settle_feature.py` | Modify | `_run` async; cosmetic queue via `asyncio.gather` |
| `src/mage/cli.py` | Modify | `cmd_run` uses `asyncio.run(graph.run(...))` |
| `tests/unit/test_events_log_lock.py` | Create | 2 tests |
| `tests/unit/test_mapping_lock.py` | Create | 2 tests |
| `tests/unit/test_cycle_lock_async.py` | Create | 3 tests |
| `tests/unit/test_inscribe_stage_async.py` | Create | 3 tests |
| `tests/unit/test_graph_async.py` | Create | 3 tests |
| `tests/features/test_e2e_concurrency.py` | Create | 2 e2e tests |

---

## Task Structure

### Task 1: HostConfig knob

**Files:**
- Modify: `src/mage/verification/host_overrides.py:23-43`

**Interfaces:**
- Produces: `HostConfig.max_concurrent_llm_calls: int = 7`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_host_config_concurrency.py
from mage.verification.host_overrides import HostConfig


def test_host_config_has_max_concurrent_llm_calls():
    cfg = HostConfig()
    assert cfg.max_concurrent_llm_calls == 7


def test_host_config_max_concurrent_llm_calls_overridable():
    cfg = HostConfig(max_concurrent_llm_calls=2)
    assert cfg.max_concurrent_llm_calls == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_host_config_concurrency.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'max_concurrent_llm_calls'`

- [ ] **Step 3: Add the field**

In `src/mage/verification/host_overrides.py`, append after line 43:

```python
    max_concurrent_llm_calls: int = 7  # Plan 8: asyncio.Semaphore cap for LLM fan-out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_host_config_concurrency.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/host_overrides.py tests/unit/test_host_config_concurrency.py
git commit -m "feat(host-config): add max_concurrent_llm_calls knob for Plan 8"
```

---

### Task 2: EventsLog async lock

**Files:**
- Modify: `src/mage/orchestration/events.py:107-130`

**Interfaces:**
- Produces: `EventsLog.append` becomes `async def`; reads stay sync; per-instance `_lock: asyncio.Lock`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_events_log_lock.py
import asyncio
from pathlib import Path

import pytest

from mage.orchestration.events import Event, EventType, EventsLog


def _evt(ts: int) -> Event:
    from datetime import datetime, UTC
    return Event(timestamp=datetime(2026, 7, 29, 12, 0, ts, tzinfo=UTC),
                 event_type=EventType.STAGE_STARTED, payload={"i": ts})


@pytest.mark.asyncio
async def test_concurrent_appends_serialize(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    await asyncio.gather(*[log.append(_evt(i)) for i in range(10)])
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 10
    payloads = [Event.model_validate_json(line).payload for line in lines]
    assert sorted(p["i"] for p in payloads) == list(range(10))


@pytest.mark.asyncio
async def test_reads_unaffected_by_writes(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    await log.append(_evt(0))
    snapshot_during = log.read_all()
    await log.append(_evt(1))
    snapshot_after = log.read_all()
    assert len(snapshot_during) == 1
    assert len(snapshot_after) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_events_log_lock.py -v`
Expected: FAIL with `TypeError: object dict can't be used in 'await' expression` (since `append` is sync)

- [ ] **Step 3: Make `append` async with lock**

In `src/mage/orchestration/events.py`, replace the `EventsLog.append` method:

```python
    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()
        self._lock: asyncio.Lock | None = None  # lazy init; asyncio.Lock can't exist at import time without a loop

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def append(self, event: Event) -> None:
        line = event.model_dump_json()
        async with self._get_lock():
            with self.log_path.open("a") as f:
                f.write(line + "\n")
```

Add `import asyncio` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_events_log_lock.py -v`
Expected: PASS (2/2)

**Important: existing tests that call `log.append(...)` synchronously will now break.** Fix them in Step 5.

- [ ] **Step 5: Update existing call sites**

Run: `grep -rn "log.append\|events_log.append\|self.events_log.append" src/mage tests/unit tests/features 2>&1 | head -50`

Update each call site: replace `events_log.append(event)` with `await events_log.append(event)`. If the enclosing function is sync, mark it `async` and propagate up. If the enclosing test is sync, use `asyncio.run(...)` or `@pytest.mark.asyncio`.

The dispatch helpers in `StageNode._emit` and `PipelineGraph._persist_halt` need `async` propagation. Use this template:

```python
# In StageNode.run():
async def run(self, context: PipelineContext) -> PipelineContext:
    await self._emit(EventType.STAGE_STARTED)
    try:
        result = await self._run(context)
        await self._emit(EventType.STAGE_COMPLETED)
        return result
    except Exception:
        raise

async def _emit(self, event_type: EventType, payload: dict | None = None) -> None:
    event = Event(...)
    await self.events_log.append(event)
```

Adjust the existing `_emit` and `run` signatures in `src/mage/orchestration/nodes.py`.

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed (after all call sites updated). If failures appear, fix the propagation chain.

- [ ] **Step 6: Commit**

```bash
git add src/mage/orchestration/events.py src/mage/orchestration/nodes.py tests/unit/test_events_log_lock.py
git add -u  # any other modified files from Step 5
git commit -m "feat(events): serialize appends via asyncio.Lock"
```

---

### Task 3: MappingArtifact save lock

**Files:**
- Modify: `src/mage/artifacts/mapping.py:222-230`

**Interfaces:**
- Produces: `MappingArtifact.save` becomes `async def`; per-instance `_lock: asyncio.Lock`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mapping_lock.py
import asyncio
from pathlib import Path

import pytest

from mage.artifacts.mapping import MappingArtifact, BaseBIDEntry


@pytest.mark.asyncio
async def test_concurrent_saves_serialize(tmp_path: Path):
    m = MappingArtifact(project_id="p", base_bids=[
        BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d"),
    ])
    paths = [tmp_path / f"m{i}.yaml" for i in range(5)]
    await asyncio.gather(*[m.save(p) for p in paths])
    for p in paths:
        loaded = MappingArtifact.load(p)
        assert loaded.project_id == "p"


@pytest.mark.asyncio
async def test_load_during_save_returns_old_or_new(tmp_path: Path):
    p = tmp_path / "m.yaml"
    m1 = MappingArtifact(project_id="p1", base_bids=[])
    m2 = MappingArtifact(project_id="p2", base_bids=[])
    await m1.save(p)
    # m1 is on disk; m2 hasn't been saved yet
    loaded = MappingArtifact.load(p)
    assert loaded.project_id == "p1"
    await m2.save(p)
    loaded = MappingArtifact.load(p)
    assert loaded.project_id == "p2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mapping_lock.py -v`
Expected: FAIL with `TypeError` (save is sync)

- [ ] **Step 3: Make `save` async with lock**

In `src/mage/artifacts/mapping.py`, replace `save`:

```python
    def __init__(self, **data) -> None:
        super().__init__(**data)
        self._save_lock: asyncio.Lock | None = None

    def _get_save_lock(self) -> asyncio.Lock:
        if self._save_lock is None:
            self._save_lock = asyncio.Lock()
        return self._save_lock

    async def save(self, path: Path) -> None:
        async with self._get_save_lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False))
            tmp_path.replace(path)
```

Add `import asyncio` at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mapping_lock.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Update existing call sites**

Run: `grep -rn "mapping.save\|\.save(mapping_path)\|new_mapping.save" src/mage tests/unit tests/features 2>&1 | head -30`

Each `mapping.save(path)` becomes `await mapping.save(path)`. Propagate async up the call chain. In `PipelineGraph.run`, every mapping.save call needs `await`. In test fixtures using sync test methods, use `asyncio.run(...)` or convert the test to async.

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mage/artifacts/mapping.py tests/unit/test_mapping_lock.py
git add -u
git commit -m "feat(mapping): serialize save via asyncio.Lock"
```

---

### Task 4: PipelineContext cycle lock + async policy

**Files:**
- Modify: `src/mage/orchestration/nodes.py` (add `_cycle_lock` field to `PipelineContext`)
- Modify: `src/mage/orchestration/discipline/policy.py` (make `acquire/release_cycle_lock` async)

**Interfaces:**
- Produces: `PipelineContext._cycle_lock: asyncio.Lock` (lazy)
- Produces: `async def acquire_cycle_lock(context, sub_bid)` and `async def release_cycle_lock(context)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cycle_lock_async.py
import asyncio
from pathlib import Path

import pytest

from mage.artifacts.mapping import (
    BaseBIDEntry, LifecycleStatus, MappingArtifact, ScenarioEntry,
)
from mage.orchestration.discipline.policy import (
    acquire_cycle_lock, release_cycle_lock,
)
from mage.orchestration.events import EventsLog
from mage.orchestration.exceptions import CycleAlreadyInProgress
from mage.orchestration.nodes import PipelineContext


def _ctx(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p", base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="b", behavior_description="d"),
        ]),
        events_log=EventsLog(tmp_path / "events.jsonl"),
    )


@pytest.mark.asyncio
async def test_acquire_blocks_until_release(tmp_path: Path):
    ctx = _ctx(tmp_path)
    await acquire_cycle_lock(ctx, "A")
    second_acquired = asyncio.Event()

    async def second():
        await acquire_cycle_lock(ctx, "B")
        second_acquired.set()

    task = asyncio.create_task(second())
    await asyncio.sleep(0.05)  # give second a chance to run
    assert not second_acquired.is_set()
    await release_cycle_lock(ctx)
    await asyncio.wait_for(task, timeout=1.0)
    assert second_acquired.is_set()


@pytest.mark.asyncio
async def test_reacquire_same_sub_bid_allowed(tmp_path: Path):
    ctx = _ctx(tmp_path)
    await acquire_cycle_lock(ctx, "A")
    await acquire_cycle_lock(ctx, "A")  # no raise


@pytest.mark.asyncio
async def test_different_sub_bid_raises_cycle_already_in_progress(tmp_path: Path):
    ctx = _ctx(tmp_path)
    await acquire_cycle_lock(ctx, "A")
    with pytest.raises(CycleAlreadyInProgress):
        await acquire_cycle_lock(ctx, "B")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cycle_lock_async.py -v`
Expected: FAIL with `TypeError: object NoneType can't be used in 'await' expression` (current acquire is sync)

- [ ] **Step 3: Add lock field to PipelineContext**

In `src/mage/orchestration/nodes.py`, add to `PipelineContext`:

```python
    _cycle_lock: asyncio.Lock | None = None

    def _get_cycle_lock(self) -> asyncio.Lock:
        if self._cycle_lock is None:
            self._cycle_lock = asyncio.Lock()
        return self._cycle_lock
```

Add `import asyncio` at the top.

- [ ] **Step 4: Make policy lock functions async**

In `src/mage/orchestration/discipline/policy.py`, replace the `acquire_cycle_lock` and `release_cycle_lock` functions:

```python
# P2 — Sequential per-scenario cycles (async)
async def acquire_cycle_lock(context: PipelineContext, sub_bid: str) -> None:
    """Acquire the cycle lock for `sub_bid`. Reacquire by same sub_bid is allowed."""
    lock = context._get_cycle_lock()
    async with lock:
        if context.current_sub_bid is not None and context.current_sub_bid != sub_bid:
            raise CycleAlreadyInProgress(
                f"cycle lock held by sub_bid {context.current_sub_bid!r}; "
                f"cannot start {sub_bid!r}"
            )
        context.current_sub_bid = sub_bid


async def release_cycle_lock(context: PipelineContext) -> None:
    """Release the cycle lock. Safe to call when unset."""
    lock = context._get_cycle_lock()
    async with lock:
        context.current_sub_bid = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cycle_lock_async.py -v`
Expected: PASS (3/3)

- [ ] **Step 6: Update existing call sites**

`tests/unit/test_discipline_policy.py` and `tests/unit/test_discipline_stage.py` use the sync versions. Update them to use `@pytest.mark.asyncio` + `await`. The `test_p2_*` tests in `test_discipline_policy.py` are the main callers. Use `asyncio.run(...)` if keeping the test sync.

Also `src/mage/orchestration/inscribe.py` and `src/mage/orchestration/discipline/stage.py` call these functions. Update to `await`.

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed.

- [ ] **Step 7: Commit**

```bash
git add src/mage/orchestration/nodes.py src/mage/orchestration/discipline/policy.py src/mage/orchestration/inscribe.py src/mage/orchestration/discipline/stage.py
git add -u
git commit -m "feat(discipline): async cycle lock with per-context asyncio.Lock"
```

---

### Task 5: StageNode base async refactor

**Files:**
- Modify: `src/mage/orchestration/nodes.py:56-94`

**Interfaces:**
- Produces: `StageNode.run` is `async def`; `StageNode._run` is `async def`; `_emit` is `async def`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_graph_async.py — first test
import asyncio
from pathlib import Path

import pytest

from mage.orchestration.events import EventType
from mage.orchestration.graph import PipelineGraph
from mage.orchestration.nodes import PipelineContext, StageNode


@pytest.mark.asyncio
async def test_graph_run_is_coroutine(tmp_path: Path):
    log = __import__("mage.orchestration.events", fromlist=["EventsLog"]).EventsLog(tmp_path / "events.jsonl")
    ctx = PipelineContext(project_dir=tmp_path, mapping=__import__("mage.artifacts.mapping", fromlist=["MappingArtifact"]).MappingArtifact(project_id="p"), events_log=log)
    stage = _StubStage(log, name="stub")
    graph = PipelineGraph(stages=[stage], events_log=log)
    result = graph.run(ctx)  # coroutine
    assert asyncio.iscoroutine(result)
    final = await result
    assert final is not None


class _StubStage(StageNode):
    name = "stub"

    async def _run(self, context):
        return context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_graph_async.py::test_graph_run_is_coroutine -v`
Expected: FAIL with `TypeError: ... not a coroutine` or similar

- [ ] **Step 3: Convert StageNode base to async**

In `src/mage/orchestration/nodes.py`, replace the StageNode class:

```python
class StageNode(ABC):
    """Abstract base for all pipeline stages.

    Subclasses must define `name` and implement `async _run()`. The base class
    emits STAGE_STARTED and STAGE_COMPLETED events around each run.
    """

    name: str = ""

    def __init__(self, events_log: EventsLog) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define `name`")
        self.events_log = events_log

    async def run(self, context: PipelineContext) -> PipelineContext:
        await self._emit(EventType.STAGE_STARTED)
        try:
            result = await self._run(context)
            await self._emit(EventType.STAGE_COMPLETED)
            return result
        except Exception:
            raise

    @abstractmethod
    async def _run(self, context: PipelineContext) -> PipelineContext:
        """Stage-specific execution. Must be implemented as async."""
        ...

    async def _emit(self, event_type: EventType, payload: dict | None = None) -> None:
        event = Event(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            payload={"stage": self.name, **(payload or {})},
        )
        await self.events_log.append(event)
```

- [ ] **Step 4: Update every StageNode subclass**

Run: `grep -rn "class.*StageNode\|def _run" src/mage/orchestration/*.py | grep -v "nodes.py"`

Every subclass needs `async def _run`. Update `InscribeStage`, `InspectFeatureStage`, `SettleFeatureStage`, `AutomationStage`, `DecomposeStage`, `EtchStage` (if exists), `RealizeStage` (if exists), `InspectLoopStage`, `DisciplineStage`. Each method body gets `await` for any I/O; pure-CPU code stays sync inside the async wrapper.

This is mechanical but spread across multiple files. Adapt each method. For methods that don't await anything, the function body stays the same — only the signature becomes `async def`.

- [ ] **Step 5: Update PipelineGraph**

Replace `PipelineGraph.run` with:

```python
    async def run(self, initial_context: PipelineContext) -> PipelineContext:
        from mage.orchestration.inscribe import ReviewBudgetExhausted

        discipline = DisciplineStage(self.events_log)
        context = initial_context
        last_seen_count = len(self.events_log.read_all())
        for stage in self.stages:
            try:
                context = await stage.run(context)
                await self._dispatch_new_events(context, discipline, [last_seen_count])
                last_seen_count = len(self.events_log.read_all())
            except ScenarioInspectHalted as e:
                # ... existing logic ...
                await self._dispatch_new_events(context, discipline, [last_seen_count])
                last_seen_count = len(self.events_log.read_all())
                raise SystemExit(0) from e
            # ... other except branches ...
        return context

    async def _dispatch_new_events(self, context, discipline, last_seen_count_ref):
        current_events = self.events_log.read_all()
        for event in current_events[last_seen_count_ref[0]:]:
            discipline._handle_event(context, event)
        last_seen_count_ref[0] = len(current_events)
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed. If failures appear in the test files, propagate async up: tests calling `graph.run(ctx)` become async + `@pytest.mark.asyncio`, OR use `asyncio.run(graph.run(ctx))` to keep them sync.

- [ ] **Step 7: Commit**

```bash
git add src/mage/orchestration/nodes.py src/mage/orchestration/graph.py
git add -u  # any stage file changes from Step 4
git commit -m "feat(orchestrator): async StageNode base + graph.run coroutine"
```

---

### Task 6: CLI asyncio.run wrapper

**Files:**
- Modify: `src/mage/cli.py:301-356` (`cmd_run`)

- [ ] **Step 1: Update `cmd_run`**

Replace the `graph.run(initial_context)` call:

```python
    graph = PipelineGraph(stages=stages, events_log=log)
    try:
        asyncio.run(graph.run(initial_context))
    except SystemExit:
        raise
    except Exception as error:
        print(f"mage run: error: {error}", file=sys.stderr)
        return 1
```

Add `import asyncio` at the top of `cli.py` if not present.

- [ ] **Step 2: Run smoke test**

Run: `uv run pytest tests/features/test_smoke.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/mage/cli.py
git commit -m "feat(cli): wrap graph.run with asyncio.run"
```

---

### Task 7: InscribeStage reviewer concurrency

**Files:**
- Modify: `src/mage/orchestration/inscribe.py:59-end`

**Interfaces:**
- Produces: `async def _run`; reviewers dispatched via `asyncio.gather` with semaphore

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inscribe_stage_async.py
import asyncio
import time
from pathlib import Path

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventType
from mage.orchestration.inscribe import InscribeStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer


@pytest.mark.asyncio
async def test_seven_reviewers_fire_concurrently(tmp_path: Path, monkeypatch):
    models.ALLOW_MODEL_REQUESTS = False

    def slow_run(self, *args, **kwargs):
        time.sleep(0.05)  # simulate LLM latency
        return self._original_run(*args, **kwargs)

    # Wrap each reviewer's _agent.run_sync to add latency and verify concurrency
    log = __import__("mage.orchestration.events", fromlist=["EventsLog"]).EventsLog(tmp_path / "events.jsonl")
    # ... setup with 7 reviewers using TestModel ...
    # ... assert wall time < 0.20s (4x single reviewer time) ...
```

This test requires careful setup. **Simpler approach**: assert that the call to `asyncio.gather` is made with all 7 reviewers in a list (mock `asyncio.gather`).

Use this simpler test:

```python
@pytest.mark.asyncio
async def test_inscribe_stage_uses_asyncio_gather_for_reviewers(tmp_path: Path, monkeypatch):
    from unittest.mock import patch, AsyncMock
    models.ALLOW_MODEL_REQUESTS = False

    # Build a minimal InscribeStage with TestModel reviewers
    log = EventsLog(tmp_path / "events.jsonl")
    # ... (use existing fixture from test_e2e_inscribe.py) ...

    with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
        await stage._run(context)
        # gather should have been called once with 7 reviewer coroutines
        assert mock_gather.call_count >= 1
        first_call_args = mock_gather.call_args_list[0].args
        assert len(first_call_args) >= 7
```

- [ ] **Step 2: Refactor InscribeStage**

Inside `InscribeStage._run`, find the loop that iterates reviewers. Replace sequential calls with:

```python
    semaphore = asyncio.Semaphore(host_config.max_concurrent_llm_calls)

    async def run_reviewer(reviewer):
        async with semaphore:
            return await reviewer.review(...)

    verdicts = await asyncio.gather(*[run_reviewer(r) for r in reviewers])
```

Reviewer's `review()` method must become async. Convert reviewer base + all 7 subclasses:

```python
# base.py
class ReviewerAgent(ABC):
    async def review(self, ...):
        ...
        return await self._agent.run(prompt)  # was run_sync
```

Replace `run_sync` with `await ... run(...)` across all 7 reviewer files.

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed. If reviewer tests fail due to missing `await`, propagate.

- [ ] **Step 4: Commit**

```bash
git add src/mage/orchestration/inscribe.py src/mage/verification/reviewers/*.py tests/unit/test_inscribe_stage_async.py
git commit -m "feat(inscribe): reviewers fire concurrently via asyncio.gather"
```

---

### Task 8: InspectFeatureStage cross-scenario concurrency

**Files:**
- Modify: `src/mage/orchestration/inspect_feature.py:68-150`

- [ ] **Step 1: Refactor InspectFeatureStage**

Find the per-scenario Inspect loop. Replace sequential with:

```python
    semaphore = asyncio.Semaphore(host_config.max_concurrent_llm_calls)

    async def run_scenario_inspect(scenario):
        async with semaphore:
            return await self._run_scenario_inspect(scenario, ...)

    results = await asyncio.gather(*[run_scenario_inspect(s) for s in scenarios])
```

- [ ] **Step 2: Update tests**

`tests/unit/test_inspect_feature.py` and `tests/features/test_e2e_inspect_settle.py` may use sync calls. Propagate async.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed.

- [ ] **Step 4: Commit**

```bash
git add src/mage/orchestration/inspect_feature.py tests/unit/test_inspect_feature.py tests/features/test_e2e_inspect_settle.py
git commit -m "feat(inspect-feature): scenarios inspect concurrently via asyncio.gather"
```

---

### Task 9: SettleFeatureStage cosmetic concurrency

**Files:**
- Modify: `src/mage/orchestration/settle_feature.py:88-160`

- [ ] **Step 1: Refactor SettleFeatureStage cosmetic queue processing**

Find where the cosmetic queue is iterated. Replace with:

```python
    semaphore = asyncio.Semaphore(host_config.max_concurrent_llm_calls)

    async def process_cosmetic(item):
        async with semaphore:
            return await self._process_cosmetic(item, ...)

    results = await asyncio.gather(*[process_cosmetic(item) for item in queue])
```

- [ ] **Step 2: Update tests + run**

Run: `uv run pytest tests/unit tests/features -q`
Expected: 381 passed.

- [ ] **Step 3: Commit**

```bash
git add src/mage/orchestration/settle_feature.py
git commit -m "feat(settle): cosmetic queue processed concurrently"
```

---

### Task 10: Final regression + whole-suite verification

- [ ] **Step 1: Run full suite**

```bash
uv run pytest tests/unit tests/features -q
```

Expected: 381 passed (existing) + ~15 new concurrency tests.

- [ ] **Step 2: Run lint/typecheck on changed files**

```bash
uv run ruff check src tests
uv run pyright src tests
```

Expected: pre-existing failures only (not introduced by Plan 8).

- [ ] **Step 3: Update CHANGELOG**

Add Plan 8 entries under `[Unreleased]`:

```markdown
### Added
- Plan 8: asyncio concurrency for LLM calls (reviewers, InspectFeature across scenarios, cosmetic queue). Configurable `max_concurrent_llm_calls` knob in HostConfig (default 7).

### Changed
- `graph.run()` and all `StageNode.run` methods are async coroutines. CLI wraps with `asyncio.run`.
- `EventsLog.append` and `MappingArtifact.save` are async with per-instance `asyncio.Lock`.

### Fixed
- Plan 7 cycle lock thread-safety: `acquire_cycle_lock` / `release_cycle_lock` are async and use a per-context `asyncio.Lock`.
```

Commit with message `docs: record Plan 8 concurrency changes in CHANGELOG`. **No `Co-Authored-By` trailer.**

---

## Spec Self-Review (post-write)

1. **Spec coverage:** All 4 spec sections (read-only parallelism, write coordination, discipline integration, HostConfig knob) mapped to tasks. asyncio.gather on three operations (reviewers, InspectFeature, cosmetic queue). Sequential-per-scenario (Plan 7 P2) preserved verbatim.
2. **Placeholder scan:** No "TBD". Task 7 reviewer-concurrency test uses `unittest.mock` on `asyncio.gather` rather than wall-time assertions (avoid flaky tests). Default `max_concurrent_llm_calls = 7` matches spec.
3. **Internal consistency:** Tasks 1-2-3 lock infrastructure before tasks 5-7-8-9 async stages. Task 4 cycle-lock conversion between. Task 6 CLI wrapper after stages. Test counts approximate (~15 new tests).
4. **Ambiguity check:** Task 5 Step 4 "Update every StageNode subclass" lists all stage classes. Task 7 Step 2 reviewer async migration is mechanical (`run_sync` → `await ... run`). Backward compat: existing sync tests use `asyncio.run(...)` wrapper if needed.
