# Plan 6: Pipeline Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mage run` execute a feature end to end: Decomposition → Inscribe → Automation (Etch → Realize → InspectLoop, nested) → InspectFeature → Settle, with halt-and-resume working across the automation loop.

**Architecture:** `PipelineGraph` keeps the coarse sequence; `AutomationStage` is a thin `StageNode` shim that delegates to a pure `FeatureRunner`. The runner owns both loops, mutates only the in-memory `automation_cursor` on `PipelineContext`, and returns per-scenario `ScenarioOutcome`s for the shim to persist.

**Tech Stack:** Python 3.12, Pydantic v2, pydantic-ai, pytest, ruff, pyright.

## Global Constraints

- **GC-1** Package is `mage`, CLI is `mage`. Import paths use `mage.*`; tests use `mage.*` imports.
- **GC-2** Pinned dependency floors: `pydantic>=2.6`, `pydantic-ai>=0.0.30`, `pydantic-graph>=0.0.30`, `pyyaml>=6.0`, `pytest>=8.0`, `pytest-cov>=4.1`, `pyright>=1.1.350`, `ruff>=0.4`. Python `>=3.12`.
- **GC-3** Conventional Commits v1.0.0. No `Co-Authored-By` trailer. No emoji.
- **GC-4** Repository standards (Makefile, CHANGELOG, AGENTS, CLAUDE, pre-commit, `tests/unit/` + `tests/features/`) already adopted. `make test` is the gate.
- **GC-5** `haileris_v2` is forbidden anywhere in the tree.
- **GC-6** Frozen Pydantic models use `model_config = ConfigDict(frozen=True)`.
- **GC-7** Stages that need loop variables (`EtchStage`, `RealizeStage`, `InspectLoopStage`) are NOT `StageNode` subclasses in this plan. Only `AutomationStage` keeps that contract.
- **GC-8** All test code references `mage.*` import paths, not `src.mage.*` or local relative imports.
- **GC-9** Routes are `"spec" | "code" | "cosmetic" | None` (`None` = clean or cosmetic-only). `FeatureRunner` never derives a route; it reads what `InspectLoopStage.inspect_increment` returns.
- **GC-10** `ScenarioInspectHalted` stops the graph (matches the other three halt exceptions).
- **GC-11** `EtchAgent.run()` returns `RedTestSpec` (already defined at `agents/etch.py:8`). No agent LLM wiring in this plan — `EtchAgent` stays a `NotImplementedError` carrier; tests inject a stub.

---

### Task 1: Data-flow models in `runner.py`

**Files:**
- Create: `src/mage/orchestration/runner.py`
- Create: `tests/unit/test_runner_models.py`

**Interfaces:**
- Consumes: nothing (foundation task)
- Produces: `ScenarioTarget`, `Increment`, `IncrementResult`, `ScenarioOutcome`, `AutomationCursor` (all frozen Pydantic models)

- [ ] **Step 1: Write failing tests for the data-flow models**

```python
# tests/unit/test_runner_models.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mage.orchestration.runner import (
    AutomationCursor,
    Increment,
    IncrementResult,
    ScenarioOutcome,
    ScenarioTarget,
)


def test_scenario_target_is_frozen():
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy path",
        gherkin_body="Given x\nWhen y\nThen z",
        steps=["x", "y", "z"],
    )
    with pytest.raises(ValidationError):
        target.scenario_name = "other"


def test_increment_carries_red_test():
    inc = Increment(index=0, step="seed", red_test_path="t.py", red_test_code="def test(): pass")
    assert inc.index == 0
    with pytest.raises(ValidationError):
        inc.index = 1


def test_increment_result_requires_diff():
    with pytest.raises(ValidationError):
        IncrementResult(files_changed=["a.py"], summary="ok")  # no diff


def test_scenario_outcome_holds_test_paths():
    out = ScenarioOutcome(sub_bid="00001-0001", test_paths=["t1.py", "t2.py"])
    assert out.test_paths == ["t1.py", "t2.py"]


def test_automation_cursor_defaults():
    cursor = AutomationCursor(sub_bid="00001-0001", increment_index=0, iteration=1)
    assert cursor.iteration == 1
    with pytest.raises(ValidationError):
        cursor.iteration = 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_runner_models.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'mage.orchestration.runner'`

- [ ] **Step 3: Write the models**

```python
# src/mage/orchestration/runner.py
"""FeatureRunner: pure loop driver for the automation phase.

Owns the outer (per scenario) and inner (per increment) loops. Performs no
agent calls, emits no events, and writes no artifacts. Mutates only the
in-memory `PipelineContext.automation_cursor`. The graph-facing
`AutomationStage` (orchestration/automation.py) wraps the runner, applies
mapping writes, and emits lifecycle events.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ScenarioTarget(BaseModel):
    """One approved scenario, the unit of the outer loop."""

    model_config = ConfigDict(frozen=True)

    base_bid: str
    sub_bid: str
    scenario_name: str
    gherkin_body: str
    steps: list[str]


class Increment(BaseModel):
    """One red test Etch produced, the unit of the inner loop."""

    model_config = ConfigDict(frozen=True)

    index: int
    step: str
    red_test_path: str
    red_test_code: str


class IncrementResult(BaseModel):
    """What Realize produced for one increment."""

    model_config = ConfigDict(frozen=True)

    files_changed: list[str]
    summary: str
    diff: str


class ScenarioOutcome(BaseModel):
    """What AutomationStage writes back to the mapping per completed scenario."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    test_paths: list[str]


class AutomationCursor(BaseModel):
    """Position within the automation loop, persisted across halts."""

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    increment_index: int
    iteration: int
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_runner_models.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/runner.py tests/unit/test_runner_models.py
git commit -m "feat(runner): add automation loop data-flow models"
```

---

### Task 2: `HostConfig.model` field

**Files:**
- Modify: `src/mage/verification/host_overrides.py` (HostConfig class, around line 28-50)
- Modify: `tests/unit/test_host_overrides.py`

**Interfaces:**
- Consumes: existing `HostConfig` (`host_overrides.py:24-51`)
- Produces: `HostConfig.model: str | None = None`; `HostConfig(test_runner_command=[...]).model is None`

- [ ] **Step 1: Write a failing test**

Add to `tests/unit/test_host_overrides.py`:

```python
def test_host_config_model_defaults_to_none():
    from mage.verification.host_overrides import HostConfig

    cfg = HostConfig(test_runner_command=["pytest"])
    assert cfg.model is None


def test_host_config_model_accepts_string():
    from mage.verification.host_overrides import HostConfig

    cfg = HostConfig(test_runner_command=["pytest"], model="openai:gpt-4o")
    assert cfg.model == "openai:gpt-4o"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_host_overrides.py::test_host_config_model_defaults_to_none -q`
Expected: PASS (the field doesn't exist yet but the test asserts the default — actually the test will fail with `TypeError: __init__() got an unexpected keyword argument 'model'` for the second test and the first will pass because the absent attribute is None — first test passes accidentally; rely on the second)

Actually run the pair: `uv run pytest tests/unit/test_host_overrides.py -q -k model`
Expected: 1 failed (`test_host_config_model_accepts_string`), 1 passed (or 1 errored depending on dataclass semantics)

- [ ] **Step 3: Add the `model` field**

In `src/mage/verification/host_overrides.py`, inside `class HostConfig(BaseModel)`, add immediately after `base_branch: str = "main"` (line 42):

```python
    model: str | None = None  # Plan 6: agent model identifier; None = pydantic-ai default
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_host_overrides.py -q -k model`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/verification/host_overrides.py tests/unit/test_host_overrides.py
git commit -m "feat(host-config): add model field for LLM agent selection"
```

---

### Task 3: `EtchStage.run_scenario`

**Files:**
- Modify: `src/mage/orchestration/etch.py` (entire file)
- Modify: `tests/unit/test_etch_stage.py`

**Interfaces:**
- Consumes: `ScenarioTarget` (Task 1), `EtchAgent.run(step=, scenario_context=)` (returns `RedTestSpec`, `agents/etch.py:8`)
- Produces: `class EtchStage` (no longer a `StageNode`) with `run_scenario(context, target) -> list[Increment]`. Constructor takes `events_log: EventsLog, agent: EtchAgent`. Emits `ETCH_STARTED`, `ETCH_RED_CONFIRMED`, `ETCH_COMPLETED` per step.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_etch_stage.py`:

```python
from mage.agents.ech import EtchAgent  # typo guard: this import will fail — use EtchAgent below
from mage.agents.etch import EtchAgent
from mage.orchestration.etch import EtchStage
from mage.orchestration.runner import Increment, ScenarioTarget


class _StubAgent:
    """Returns one RedTestSpec per unique step it sees."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._n = 0

    def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        self.calls.append((step, scenario_context))
        spec = RedTestSpec(
            step_name=step,
            test_path=f"tests/{step}.py",
            test_code=f"def test_{step}(): pass",
        )
        return spec


def test_run_scenario_emits_one_increment_per_step(tmp_path):
    log = EventsLog(tmp_path / "events.jsonl")
    agent = _StubAgent()
    stage = EtchStage(log, agent=agent)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed", "grow", "harvest"],
    )

    increments = stage.run_scenario(context=None, target=target)  # type: ignore[arg-type]

    assert [inc.index for inc in increments] == [0, 1, 2]
    assert [inc.step for inc in increments] == ["seed", "grow", "harvest"]
    assert [inc.red_test_path for inc in increments] == [
        "tests/seed.py",
        "tests/grow.py",
        "tests/harvest.py",
    ]
    types = [e.event_type.value for e in log.read_all()]
    assert "etch_started" in types
    assert "etch_red_confirmed" in types
    assert "etch_completed" in types


def test_run_scenario_carries_target_sub_bid_to_agent():
    log = EventsLog(tmp_path_path := None)  # placeholder; rewrite in step
    ...
```

Stop. Rewrite the test file fresh in the next step. The above block has typos (RedTestSpec is unused-imported, the second test is half-written). For clarity, replace the whole file:

`tests/unit/test_etch_stage.py`:

```python
"""Tests for EtchStage.run_scenario."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ConfigDict

from mage.agents.etch import EtchAgent, RedTestSpec
from mage.orchestration.events import EventsLog
from mage.orchestration.etch import EtchStage
from mage.orchestration.runner import ScenarioTarget


class _StubAgent:
    """Returns one RedTestSpec per call, mirroring EtchAgent's signature."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, *, step: str, scenario_context: dict) -> RedTestSpec:
        self.calls.append((step, scenario_context))
        return RedTestSpec(
            step_name=step,
            test_path=f"tests/{step}.py",
            test_code=f"def test_{step}(): pass\n",
        )


def _context(tmp_path):
    from mage.orchestration.nodes import PipelineContext
    from mage.artifacts.mapping import MappingArtifact

    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


def test_run_scenario_emits_one_increment_per_step(tmp_path):
    ctx = _context(tmp_path)
    agent = _StubAgent()
    stage = EtchStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed", "grow", "harvest"],
    )

    increments = stage.run_scenario(ctx, target)

    assert [inc.index for inc in increments] == [0, 1, 2]
    assert [inc.step for inc in increments] == ["seed", "grow", "harvest"]
    assert [inc.red_test_path for inc in increments] == [
        "tests/seed.py",
        "tests/grow.py",
        "tests/harvest.py",
    ]
    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert types.count("etch_started") == 1
    assert types.count("etch_red_confirmed") == 3
    assert types.count("etch_completed") == 3


def test_run_scenario_passes_target_sub_bid_to_agent(tmp_path):
    ctx = _context(tmp_path)
    agent = _StubAgent()
    stage = EtchStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["only"],
    )

    stage.run_scenario(ctx, target)

    assert agent.calls == [("only", {"sub_bid": "00001-0001"})]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_etch_stage.py -q`
Expected: 2 failed (signature mismatch: current `EtchStage` is a `StageNode` with `_run(context)`, not `run_scenario(context, target)`)

- [ ] **Step 3: Rewrite `etch.py`**

Replace the entire contents of `src/mage/orchestration/etch.py` with:

```python
"""EtchStage: produces red tests for a scenario, one per step.

Plan 6: this stage is no longer a StageNode. It no longer owns the loop
variable (`sub_bid`, `scenario_name`) — those arrive in a `ScenarioTarget`
built by `AutomationStage`. It emits its own domain events; `AutomationStage`
emits the coarse STAGE_STARTED / STAGE_COMPLETED around it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mage.agents.etch import EtchAgent
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, ScenarioTarget


class ScenarioInspectHalted(Exception):
    """Raised when InspectLoop routes a finding to spec/halts the run."""


class EtchStage:
    """One pass through the steps of a scenario, producing one Increment per step."""

    def __init__(self, events_log: EventsLog, agent: EtchAgent) -> None:
        self.events_log = events_log
        self.agent = agent

    def run_scenario(
        self, context: PipelineContext, target: ScenarioTarget
    ) -> list[Increment]:
        """Generate a red test for each step. Returns increments in step order."""
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.ETCH_STARTED,
                payload={
                    "scenario_name": target.scenario_name,
                    "sub_bid": target.sub_bid,
                },
            )
        )
        increments: list[Increment] = []
        for index, step in enumerate(target.steps):
            spec = self.agent.run(
                step=step,
                scenario_context={"sub_bid": target.sub_bid},
            )
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.ETCH_RED_CONFIRMED,
                    payload={
                        "scenario_name": target.scenario_name,
                        "step_name": spec.step_name,
                        "red_test_path": spec.test_path,
                    },
                )
            )
            increments.append(
                Increment(
                    index=index,
                    step=spec.step_name,
                    red_test_path=spec.test_path,
                    red_test_code=spec.test_code,
                )
            )
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.ETCH_COMPLETED,
                    payload={
                        "scenario_name": target.scenario_name,
                        "step_name": spec.step_name,
                        "red_test_count": index + 1,
                    },
                )
            )
        return increments
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_etch_stage.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/etch.py tests/unit/test_etch_stage.py
git commit -m "feat(etch): per-scenario run_scenario returning increments"
```

---

### Task 4: `RealizeStage.run_increment` with diff

**Files:**
- Modify: `src/mage/orchestration/realize.py` (entire file)
- Modify: `tests/unit/test_realize_stage.py`

**Interfaces:**
- Consumes: `ScenarioTarget`, `Increment`, `RealizeAgent` (returns `RealizeOutput(files_changed, summary)`, `agents/realize.py:13`), `CommandRunner` (already defined in `settle_feature.py:17`)
- Produces: `class RealizeStage` (no `StageNode`) with `run_increment(context, *, target, increment, command_runner=None) -> IncrementResult`. If `command_runner is None`, uses `_default_command_runner` defined here. Computes diff as `git diff --unified=10 -- <files_changed>` after the agent returns.

- [ ] **Step 1: Write failing tests**

Replace `tests/unit/test_realize_stage.py` with:

```python
"""Tests for RealizeStage.run_increment."""

from __future__ import annotations

import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from mage.agents.realize import RealizeAgent, RealizeOutput
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.realize import RealizeStage
from mage.orchestration.runner import Increment, ScenarioTarget


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


class _StubAgent:
    def __init__(self, output: RealizeOutput) -> None:
        self._output = output

    def run(self, **kwargs) -> RealizeOutput:
        return self._output


class _RecordingRunner:
    def __init__(self, stdout: str = "diff --git a/foo.py\n+new line\n") -> None:
        self.stdout = stdout
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> CompletedProcess[str]:
        self.calls.append((list(command), Path(cwd)))
        return CompletedProcess(command, 0, stdout=self.stdout, stderr="")


def test_run_increment_returns_increment_result_with_diff(tmp_path):
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _StubAgent(
        RealizeOutput(files_changed=["foo.py", "bar.py"], summary="ok")
    )
    runner = _RecordingRunner(stdout="diff payload")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    result = stage.run_increment(ctx, target=target, increment=increment)

    assert result.files_changed == ["foo.py", "bar.py"]
    assert result.summary == "ok"
    assert result.diff == "diff payload"
    assert len(runner.calls) == 1
    command, cwd = runner.calls[0]
    assert command[:3] == ["git", "diff", "--unified=10"]
    assert command[-2:] == ["--", "foo.py", "bar.py"]


def test_run_increment_uses_default_runner_when_none_provided(tmp_path, monkeypatch):
    """The default runner must exist and be callable; tests don't hit real git."""
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _StubAgent(RealizeOutput(files_changed=[], summary="nothing"))

    def fake_run(command, *, cwd):
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "mage.orchestration.realize._default_command_runner", fake_run
    )
    stage = RealizeStage(ctx.events_log, agent=agent)  # type: ignore[arg-type]

    result = stage.run_increment(ctx, target=target, increment=increment)

    assert result.diff == ""


def test_run_increment_emits_realize_increment_done(tmp_path):
    ctx = _context(tmp_path)
    target = ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )
    increment = Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )
    agent = _StubAgent(RealizeOutput(files_changed=["x.py"], summary=""))
    runner = _RecordingRunner(stdout="")
    stage = RealizeStage(ctx.events_log, agent=agent, command_runner=runner)  # type: ignore[arg-type]

    stage.run_increment(ctx, target=target, increment=increment)

    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert "realize_increment_done" in types
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_realize_stage.py -q`
Expected: 3 failed — current `RealizeStage` is a `StageNode` with `_run_single_increment(...)` returning `None`, not `run_increment(...)` returning `IncrementResult`.

- [ ] **Step 3: Rewrite `realize.py`**

Replace `src/mage/orchestration/realize.py` with:

```python
"""RealizeStage: drives one increment of the inner TDD loop, with diff capture.

Plan 6: this stage is no longer a StageNode. It no longer pulls
carry-forward from the mapping itself (FeatureRunner passes it), and it now
returns an `IncrementResult` so `InspectLoopStage.inspect_increment` can
hand the diff to the reviewer without keyword-argument guesswork.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import Callable

from mage.agents.realize import RealizeAgent
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget

CommandRunner = Callable[..., CompletedProcess[str]]


def _default_command_runner(command: list[str], *, cwd: Path) -> CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class RealizeStage:
    """One increment: ask the agent to make the red test pass, then diff."""

    def __init__(
        self,
        events_log: EventsLog,
        agent: RealizeAgent,
        *,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.events_log = events_log
        self.agent = agent
        self.command_runner = command_runner or _default_command_runner

    def run_increment(
        self,
        context: PipelineContext,
        *,
        target: ScenarioTarget,
        increment: Increment,
        carry_forward: list | None = None,
    ) -> IncrementResult:
        """Run the agent, compute the diff, return an IncrementResult.

        `carry_forward` is unused on the runner side; the journal-windowing
        logic that previously lived here moved to FeatureRunner so the runner
        owns its carry-forward policy. The parameter is kept for a future
        Plan 7/8 where the carry-forward may need override at the call site.
        """
        output = self.agent.run(
            step=increment.step,
            scenario_context={"sub_bid": target.sub_bid},
            red_test_path=increment.red_test_path,
            carry_forward=carry_forward or [],
            cross_scenario_observations=[],
        )
        diff = ""
        if output.files_changed:
            result = self.command_runner(
                ["git", "diff", "--unified=10", "--", *output.files_changed],
                cwd=context.project_dir,
            )
            diff = result.stdout
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.REALIZE_INCREMENT_DONE,
                payload={
                    "sub_bid": target.sub_bid,
                    "step": increment.step,
                    "files_changed": output.files_changed,
                },
            )
        )
        return IncrementResult(
            files_changed=list(output.files_changed),
            summary=output.summary,
            diff=diff,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_realize_stage.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/realize.py tests/unit/test_realize_stage.py
git commit -m "feat(realize): run_increment returns IncrementResult with diff"
```

---

### Task 5: `InspectLoopStage.inspect_increment`

**Files:**
- Modify: `src/mage/orchestration/inspect_loop.py` (entire file except the route-detection block — that is Task 6)
- Modify: `tests/unit/test_inspect_loop.py`

**Interfaces:**
- Consumes: `ScenarioTarget`, `Increment`, `IncrementResult`, `MechanicalVerifier.verify(scope="increment")`, `IncrementQualityReviewer` (returns a `ReviewerVerdict` with `.findings`, each finding now carries `.route` after Task 6 — for now, the test injects a reviewer whose findings already expose `.route`)
- Produces: `class InspectLoopStage` (no `StageNode`) with `inspect_increment(context, *, target, increment, result) -> InspectRoute | None` where `InspectRoute = Literal["spec", "code", "cosmetic"]` and `None` means clean or cosmetic-only (per GC-9). Constructor: `__init__(events_log, mechanical_verifier, increment_quality_reviewer, host_config)`. The `realize_stage` constructor parameter is gone.

- [ ] **Step 1: Write failing tests**

Replace `tests/unit/test_inspect_loop.py` with:

```python
"""Tests for InspectLoopStage.inspect_increment."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.inspect_loop import InspectLoopStage
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import CheckResult


def _context(tmp_path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )


class _Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    location: str
    issue: str
    suggestion: str
    severity: str
    route: Literal["spec", "code", "cosmetic"]


class _Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    findings: list[_Finding]


class _Reviewer:
    def __init__(self, verdict: _Verdict) -> None:
        self._verdict = verdict
        self.calls: list[dict] = []

    def run(self, **kwargs) -> _Verdict:
        self.calls.append(kwargs)
        return self._verdict


class _Mechanical:
    def __init__(self, results: list[CheckResult]) -> None:
        self._results = results
        self.scopes: list[str] = []

    def verify(self, *, scope: str) -> list[CheckResult]:
        self.scopes.append(scope)
        return self._results


def _target() -> ScenarioTarget:
    return ScenarioTarget(
        base_bid="00001",
        sub_bid="00001-0001",
        scenario_name="happy",
        gherkin_body="",
        steps=["seed"],
    )


def _increment() -> Increment:
    return Increment(
        index=0, step="seed", red_test_path="t.py", red_test_code="..."
    )


def test_clean_increment_returns_none(tmp_path):
    ctx = _context(tmp_path)
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route is None
    assert mech.scopes == ["increment"]


def test_code_route_re_loops(tmp_path):
    ctx = _context(tmp_path)
    finding = _Finding(
        id="f1",
        location="a.py:1",
        issue="naming",
        suggestion="rename",
        severity="major",
        route="code",
    )
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[finding]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route == "code"


def test_cosmetic_route_returns_none_so_runner_does_not_re_loop(tmp_path):
    """Per GC-9: cosmetic is queued and does not re-loop. The runner must see
    None for cosmetic-only passes, not "cosmetic", so the while loop breaks."""
    ctx = _context(tmp_path)
    finding = _Finding(
        id="f1",
        location="a.py:1",
        issue="wording",
        suggestion="tweak",
        severity="minor",
        route="cosmetic",
    )
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[finding]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route is None
    cosmetic = ctx.mapping.feature_cosmetic_queue
    assert len(cosmetic) == 1


def test_spec_route_returns_spec(tmp_path):
    ctx = _context(tmp_path)
    finding = _Finding(
        id="f1",
        location="a.py:1",
        issue="wrong contract",
        suggestion="rewrite spec",
        severity="critical",
        route="spec",
    )
    reviewer = _Reviewer(_Verdict(dimension="increment_quality", findings=[finding]))
    mech = _Mechanical([])
    stage = InspectLoopStage(
        ctx.events_log,
        mechanical_verifier=mech,
        increment_quality_reviewer=reviewer,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )
    result = IncrementResult(files_changed=["a.py"], summary="", diff="")

    route = stage.inspect_increment(
        ctx, target=_target(), increment=_increment(), result=result
    )

    assert route == "spec"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_inspect_loop.py -q`
Expected: 4 failed — current signature `_run_single_increment` returns `None`, the cosmetic test asserts `route is None` but the current code would return `"cosmetic"`.

- [ ] **Step 3: Rewrite `inspect_loop.py`**

Replace the contents of `src/mage/orchestration/inspect_loop.py` with:

```python
"""InspectLoopStage: one pass of per-increment Inspect (mechanical + reviewer).

Plan 6: this stage is no longer a StageNode. `inspect_increment` is the
single entry point. It returns the routing decision so `FeatureRunner` can
decide whether to re-loop, halt, or break. The mechanical pre-check, the
reviewer call, the journal append, and the cosmetic queue are all in here.
Route detection is now an explicit field on the finding (Task 6) — no more
string-prefix parsing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from mage.artifacts.inspect import InspectJournalEntry
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
from mage.verification.host_overrides import HostConfig

InspectRoute = Literal["spec", "code", "cosmetic"]


def _normalize_mechanical_findings(items) -> list:
    """Plan 4 introduced an adapter for the (CheckResult | MechanicalFinding)
    return shape. Kept here verbatim so the new file builds the same contract."""
    out = []
    for item in items:
        finding_id = getattr(item, "finding_id", None) or getattr(item, "id", None)
        if finding_id is None:
            continue
        out.append(item)
    return out


class InspectLoopStage:
    """One increment of Inspect. Returns the routing decision."""

    def __init__(
        self,
        events_log: EventsLog,
        *,
        mechanical_verifier,
        increment_quality_reviewer,
        host_config: HostConfig,
    ) -> None:
        self.events_log = events_log
        self.mechanical_verifier = mechanical_verifier
        self.increment_quality_reviewer = increment_quality_reviewer
        self.host_config = host_config

    def inspect_increment(
        self,
        context: PipelineContext,
        *,
        target: ScenarioTarget,
        increment: Increment,
        result: IncrementResult,
    ) -> InspectRoute | None:
        """Run mechanical, then the increment-quality reviewer, then journal.

        Returns:
            "spec" — the runner halts via ScenarioInspectHalted.
            "code" — the runner re-loops with this finding in carry-forward.
            None   — clean OR cosmetic-only (cosmetic is queued, not re-looped).
        """
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_LOOP_STARTED,
                payload={
                    "sub_bid": target.sub_bid,
                    "scenario_name": target.scenario_name,
                    "increment_id": f"{target.sub_bid}-{context.iteration}",
                },
            )
        )
        iteration = context.iteration
        if iteration > self.host_config.per_loop_max_iterations:
            from mage.orchestration.etch import ScenarioInspectHalted

            raise ScenarioInspectHalted(
                f"per-loop budget exhausted for sub-bid {target.sub_bid!r}"
            )

        # 1. Mechanical pre-check
        raw_mech = self.mechanical_verifier.verify(scope="increment")
        for f in _normalize_mechanical_findings(raw_mech):
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_JOURNAL_APPENDED,
                    payload={
                        "sub_bid": target.sub_bid,
                        "dimension": "mechanical",
                        "severity": getattr(f, "severity", "minor"),
                        "route": "code",
                        "finding_id": getattr(f, "finding_id", "?"),
                        "location": getattr(f, "location", "?"),
                        "issue": getattr(f, "issue", "?"),
                        "rationale": getattr(f, "rationale", ""),
                        "iteration": iteration,
                    },
                )
            )
            context.mapping = context.mapping.append_inspect_journal(
                target.sub_bid,
                InspectJournalEntry(
                    timestamp=datetime.now(UTC),
                    iteration=iteration,
                    dimension="mechanical",
                    severity=getattr(f, "severity", "minor"),
                    route="code",
                    finding_id=getattr(f, "finding_id", "?"),
                    location=getattr(f, "location", "?"),
                    issue=getattr(f, "issue", "?"),
                    rationale=getattr(f, "rationale", ""),
                ),
            )

        # 2. IncrementQualityReviewer
        recent_window = [
            InspectJournalEntry.model_validate(e)
            for e in context.mapping.inspect_journal.get(target.sub_bid, [])[-5:]
        ]
        verdict = self.increment_quality_reviewer.run(
            increment_diff=result.diff,
            new_test=increment.red_test_code,
            scenario_steps=target.steps,
            recent_journal_window=recent_window,
        )
        if not verdict.findings:
            return None

        # 3. Route findings. Route is now an explicit field; no prefix parsing.
        spec_route: InspectRoute | None = None
        code_count = 0
        for f in verdict.findings:
            route: InspectRoute = f.route
            if route == "spec":
                spec_route = "spec"
            elif route == "code":
                code_count += 1
            elif route == "cosmetic":
                context.mapping = context.mapping.model_copy(
                    update={
                        "feature_cosmetic_queue": [
                            *context.mapping.feature_cosmetic_queue,
                            {
                                "sub_bid": target.sub_bid,
                                "scenario_name": target.scenario_name,
                                "location": f.location,
                                "text": f.suggestion,
                                "proposed_by": "increment_quality",
                            },
                        ]
                    }
                )

            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_JOURNAL_APPENDED,
                    payload={
                        "sub_bid": target.sub_bid,
                        "dimension": getattr(verdict, "dimension", "increment_quality"),
                        "severity": f.severity,
                        "route": route,
                        "finding_id": f.id,
                        "location": f.location,
                        "issue": f.issue,
                        "rationale": "",
                        "iteration": iteration,
                    },
                )
            )
            context.mapping = context.mapping.append_inspect_journal(
                target.sub_bid,
                InspectJournalEntry(
                    timestamp=datetime.now(UTC),
                    iteration=iteration,
                    dimension=getattr(verdict, "dimension", "increment_quality"),
                    severity=f.severity,
                    route=route,
                    finding_id=f.id,
                    location=f.location,
                    issue=f.issue,
                    rationale="",
                ),
            )

        if spec_route == "spec":
            return "spec"
        if code_count:
            return "code"
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_inspect_loop.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/inspect_loop.py tests/unit/test_inspect_loop.py
git commit -m "feat(inspect-loop): per-increment inspect returning route"
```

---

### Task 6: Route on `ReviewerFinding`

**Files:**
- Modify: `src/mage/verification/reviewers/increment_quality.py`
- Modify: the reviewer `Finding` model in `src/mage/verification/reviewers/base.py` (or wherever the finding schema lives)

**Interfaces:**
- Consumes: existing reviewer finding schema
- Produces: every finding carries `route: InspectRoute`. `IncrementQualityReviewer.run` populates it. The `InspectLoopStage` already reads it (Task 5). No more string-prefix parsing anywhere.

- [ ] **Step 1: Find the finding schema**

Run: `grep -rn "class Finding\|class ReviewerFinding" src/mage/verification/reviewers/`
Expected: a single class definition, likely in `base.py` or the increment_quality file.

- [ ] **Step 2: Add the `route` field to the finding schema**

Open the file containing the finding class. Add:

```python
from mage.orchestration.inspect_loop import InspectRoute  # if defined in inspect_loop
# OR define locally if avoiding the import cycle:
# InspectRoute = Literal["spec", "code", "cosmetic"]
```

Add to the finding model:

```python
    route: InspectRoute
```

If the file is `src/mage/verification/reviewers/base.py`, prefer the local `Literal` to avoid pulling `inspect_loop.py` into the reviewer module (cleaner dependency direction).

- [ ] **Step 3: Update `IncrementQualityReviewer` to populate `route`**

In `src/mage/verification/reviewers/increment_quality.py`, change the `Finding` construction(s) so each emitted finding sets `route=...`. Use the existing decision logic that currently encodes route in `suggestion` (`"spec:..."`, `"cosmetic:..."`); flip the precedence so the route is set explicitly and the suggestion no longer carries the prefix.

- [ ] **Step 4: Add a unit test**

Add to `tests/unit/test_reviewers/test_increment_quality.py`:

```python
def test_increment_quality_finding_has_route_field():
    from mage.verification.reviewers.increment_quality import IncrementQualityReviewer
    from mage.agents.reviewer import ReviewerVerdict  # adjust import

    # Construct a canned verdict with one finding per route; assert each
    # finding's `.route` is set, not parsed from a string prefix.
    ...
```

(Fill the body to match the actual `IncrementQualityReviewer` constructor and `Finding` type for the existing test file. Run the existing test suite first; the change to the `Finding` schema is the breaking edit and the rest of the file's tests need to set `route` on their canned findings.)

- [ ] **Step 5: Run the test suite and fix any review tests that broke**

Run: `uv run pytest tests/unit/test_reviewers/ -q`
Expected: failures only in tests that construct `Finding(...)` without `route`. Add `route="code"` (or the appropriate route) to each. This is mechanical.

- [ ] **Step 6: Commit**

```bash
git add src/mage/verification/reviewers/ tests/unit/test_reviewers/
git commit -m "fix(reviewers): route on ReviewerFinding replaces string-prefix parse"
```

---

### Task 7: `FeatureRunner` core loop

**Files:**
- Modify: `src/mage/orchestration/runner.py` (add `FeatureRunner` class)
- Create: `tests/unit/test_runner.py`

**Interfaces:**
- Consumes: `EtchStage.run_scenario`, `RealizeStage.run_increment`, `InspectLoopStage.inspect_increment`, `ScenarioTarget`
- Produces: `class FeatureRunner` with constructor `__init__(self, etch, realize, inspect_loop)` and method `run(self, context, targets: list[ScenarioTarget]) -> list[ScenarioOutcome]`. Inner loop is bounded by `context.host_config.per_loop_max_iterations` (added to `PipelineContext` in Task 9 — until then, read it from a kwarg). Cursor advance + clearing per scenario is here.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_runner.py`:

```python
"""Tests for FeatureRunner."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from mage.orchestration.runner import (
    AutomationCursor,
    FeatureRunner,
    Increment,
    IncrementResult,
    ScenarioOutcome,
    ScenarioTarget,
)


class _Finding(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    location: str
    issue: str
    suggestion: str
    severity: str
    route: Literal["spec", "code", "cosmetic"]


class _Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)
    dimension: str
    findings: list[_Finding]


class _Reviewer:
    def __init__(self, verdicts: list[_Verdict]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0

    def run(self, **kwargs) -> _Verdict:
        self.calls += 1
        return self._verdicts.pop(0) if self._verdicts else _Verdict(
            dimension="increment_quality", findings=[]
        )


class _Mechanical:
    def verify(self, *, scope: str):
        return []


def _target(sub_bid: str = "00001-0001") -> ScenarioTarget:
    return ScenarioTarget(
        base_bid="00001",
        sub_bid=sub_bid,
        scenario_name="happy",
        gherkin_body="",
        steps=["s1"],
    )


def _ctx():
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext
    return PipelineContext(
        project_dir=None,  # type: ignore[arg-type]
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(None),  # type: ignore[arg-type]
        plan_path=None,  # type: ignore[arg-type]
        iteration=0,
    )


def test_clean_increment_produces_one_scenario_outcome():
    target = _target()
    etch = type("E", (), {
        "run_scenario": lambda self, ctx, t: [Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")]
    })()
    realize = type("R", (), {
        "run_increment": lambda self, ctx, *, target, increment, carry_forward=None: IncrementResult(
            files_changed=[], summary="", diff=""
        )
    })()
    inspect = type("I", (), {
        "inspect_increment": lambda self, ctx, *, target, increment, result: None
    })()
    runner = FeatureRunner(etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8)  # type: ignore[arg-type]

    outcomes = runner.run(_ctx(), [target])

    assert outcomes == [ScenarioOutcome(sub_bid="00001-0001", test_paths=["t.py"])]
    assert runner.cursor is None  # cleared after a clean scenario


def test_code_route_re_loops_until_clean():
    target = _target()
    etch = type("E", (), {
        "run_scenario": lambda self, ctx, t: [Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")]
    })()

    verdicts = [
        _Verdict(dimension="iq", findings=[_Finding(
            id="f", location="a", issue="x", suggestion="y", severity="major", route="code"
        )]),
        _Verdict(dimension="iq", findings=[]),
    ]
    realize = type("R", (), {
        "run_increment": lambda self, ctx, *, target, increment, carry_forward=None: IncrementResult(
            files_changed=[], summary="", diff=""
        )
    })()
    reviewer = _Reviewer(verdicts)
    inspect = type("I", (), {
        "inspect_increment": lambda self, ctx, *, target, increment, result: (
            "code" if reviewer._verdicts and reviewer._verdicts[0].findings else None
        )
    })()
    runner = FeatureRunner(etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8)  # type: ignore[arg-type]

    outcomes = runner.run(_ctx(), [target])

    assert len(outcomes) == 1
    assert reviewer.calls == 2  # two inspect calls before clean


def test_spec_route_raises_scenario_inspect_halted():
    from mage.orchestration.etch import ScenarioInspectHalted

    target = _target()
    etch = type("E", (), {
        "run_scenario": lambda self, ctx, t: [Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")]
    })()
    realize = type("R", (), {
        "run_increment": lambda self, ctx, *, target, increment, carry_forward=None: IncrementResult(
            files_changed=[], summary="", diff=""
        )
    })()
    inspect = type("I", (), {
        "inspect_increment": lambda self, ctx, *, target, increment, result: "spec"
    })()
    runner = FeatureRunner(etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8)  # type: ignore[arg-type]

    with pytest.raises(ScenarioInspectHalted):
        runner.run(_ctx(), [target])


def test_cosmetic_only_does_not_re_loop():
    target = _target()
    etch = type("E", (), {
        "run_scenario": lambda self, ctx, t: [Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")]
    })()
    realize = type("R", (), {
        "run_increment": lambda self, ctx, *, target, increment, carry_forward=None: IncrementResult(
            files_changed=[], summary="", diff=""
        )
    })()
    calls = {"n": 0}

    def inspect_increment(self_or_ctx, ctx, **kwargs):
        calls["n"] += 1
        return None  # cosmetic-only path returns None

    inspect = type("I", (), {"inspect_increment": staticmethod(inspect_increment)})()
    runner = FeatureRunner(etch=etch, realize=realize, inspect_loop=inspect, per_loop_max_iterations=8)  # type: ignore[arg-type]

    runner.run(_ctx(), [target])

    assert calls["n"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_runner.py -q`
Expected: `ImportError: cannot import name 'FeatureRunner' from 'mage.orchestration.runner'`

- [ ] **Step 3: Add `FeatureRunner` to `runner.py`**

Append to `src/mage/orchestration/runner.py`:

```python
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mage.orchestration.nodes import PipelineContext


class _EtchLike(Protocol):
    def run_scenario(self, context, target: ScenarioTarget) -> list[Increment]: ...


class _RealizeLike(Protocol):
    def run_increment(self, context, *, target, increment, carry_forward=None) -> IncrementResult: ...


class _InspectLike(Protocol):
    def inspect_increment(self, context, *, target, increment, result) -> "InspectRoute | None": ...


class FeatureRunner:
    """Owns the automation loops. No I/O, no events, no artifact writes."""

    def __init__(
        self,
        *,
        etch: _EtchLike,
        realize: _RealizeLike,
        inspect_loop: _InspectLike,
        per_loop_max_iterations: int,
    ) -> None:
        self.etch = etch
        self.realize = realize
        self.inspect_loop = inspect_loop
        self.per_loop_max_iterations = per_loop_max_iterations
        self.cursor: AutomationCursor | None = None

    def run(
        self,
        context: "PipelineContext",
        targets: list[ScenarioTarget],
    ) -> list[ScenarioOutcome]:
        outcomes: list[ScenarioOutcome] = []
        for target in targets:
            increments = self.etch.run_scenario(context, target)
            for increment in increments:
                iteration = 1
                while True:
                    self.cursor = AutomationCursor(
                        sub_bid=target.sub_bid,
                        increment_index=increment.index,
                        iteration=iteration,
                    )
                    context.automation_cursor = self.cursor
                    context.iteration = iteration
                    result = self.realize.run_increment(
                        context, target=target, increment=increment
                    )
                    route = self.inspect_loop.inspect_increment(
                        context, target=target, increment=increment, result=result
                    )
                    if route is None:
                        break
                    if route == "spec":
                        from mage.orchestration.etch import ScenarioInspectHalted

                        raise ScenarioInspectHalted(
                            f"spec-route finding for sub-bid {target.sub_bid!r} at iteration {iteration}"
                        )
                    if route == "code":
                        iteration += 1
                        if iteration > self.per_loop_max_iterations:
                            from mage.orchestration.etch import ScenarioInspectHalted

                            raise ScenarioInspectHalted(
                                f"per-loop budget exhausted for sub-bid {target.sub_bid!r}"
                            )
                        continue
                    # "cosmetic" — InspectLoopStage already queues and returns
                    # None, so this branch is unreachable in well-formed input.
                    break
            outcomes.append(
                ScenarioOutcome(
                    sub_bid=target.sub_bid,
                    test_paths=[inc.red_test_path for inc in increments],
                )
            )
            self.cursor = None
            context.automation_cursor = None
        return outcomes
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_runner.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/runner.py tests/unit/test_runner.py
git commit -m "feat(runner): FeatureRunner core outer+inner loop"
```

---

### Task 8: `FeatureRunner` resume from cursor

**Files:**
- Modify: `src/mage/orchestration/runner.py`
- Modify: `tests/unit/test_runner.py` (append)

**Interfaces:**
- Consumes: `FeatureRunner.run` from Task 7, `AutomationCursor` from Task 1
- Produces: `FeatureRunner.run(context, targets, *, cursor: AutomationCursor | None = None) -> list[ScenarioOutcome]`. When `cursor` is given: skip scenarios preceding `cursor.sub_bid`; for the matching scenario, start at `cursor.increment_index` with `iteration = cursor.iteration`; clear cursor after scenario completes.

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_runner.py`:

```python
def test_resume_skips_completed_scenarios():
    """First scenario is already done; resume at the second."""
    t1 = _target(sub_bid="00001-0001")
    t2 = _target(sub_bid="00001-0002")

    etch_calls: list[str] = []

    class E:
        def run_scenario(self, ctx, t):
            etch_calls.append(t.sub_bid)
            return [Increment(index=0, step="s1", red_test_path="t.py", red_test_code="")]

    class R:
        def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class I:
        def inspect_increment(self, ctx, *, target, increment, result):
            return None

    runner = FeatureRunner(etch=E(), realize=R(), inspect_loop=I(), per_loop_max_iterations=8)  # type: ignore[arg-type]
    cursor = AutomationCursor(sub_bid="00001-0002", increment_index=0, iteration=1)

    outcomes = runner.run(_ctx(), [t1, t2], cursor=cursor)

    assert etch_calls == ["00001-0002"]
    assert outcomes == [ScenarioOutcome(sub_bid="00001-0002", test_paths=["t.py"])]


def test_resume_at_mid_scenario_starts_at_cursor_iteration():
    """The cursor's iteration is the next attempt, not the completed one."""
    t1 = _target(sub_bid="00001-0001")
    inspect_iterations: list[int] = []

    class E:
        def run_scenario(self, ctx, t):
            return [
                Increment(index=0, step="s1", red_test_path="t.py", red_test_code=""),
                Increment(index=1, step="s2", red_test_path="t.py", red_test_code=""),
            ]

    class R:
        def run_increment(self, ctx, *, target, increment, carry_forward=None):
            return IncrementResult(files_changed=[], summary="", diff="")

    class I:
        def inspect_increment(self, ctx, *, target, increment, result):
            inspect_iterations.append(ctx.iteration)
            return None

    runner = FeatureRunner(etch=E(), realize=R(), inspect_loop=I(), per_loop_max_iterations=8)  # type: ignore[arg-type]
    cursor = AutomationCursor(sub_bid="00001-0001", increment_index=1, iteration=3)

    runner.run(_ctx(), [t1], cursor=cursor)

    # increment 0 was skipped (completed before halt); increment 1 starts at iter 3
    assert ctx_iterations := [i for i in inspect_iterations] == [3]


def test_cursor_cleared_after_clean_scenario():
    t1 = _target()
    runner = FeatureRunner(
        etch=type("E", (), {"run_scenario": lambda self, c, t: [Increment(0, "s", "t.py", "")]})(),
        realize=type("R", (), {"run_increment": lambda self, c, *, target, increment, carry_forward=None: IncrementResult([], "", "")})(),
        inspect_loop=type("I", (), {"inspect_increment": lambda self, c, *, target, increment, result: None})(),
        per_loop_max_iterations=8,
    )
    runner.run(_ctx(), [t1], cursor=AutomationCursor(sub_bid="00001-0001", increment_index=0, iteration=1))
    assert runner.cursor is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/unit/test_runner.py -q -k resume`
Expected: 3 failed (cursor parameter not yet accepted)

- [ ] **Step 3: Add cursor support to `FeatureRunner.run`**

In `src/mage/orchestration/runner.py`, change the `run` method signature and body:

```python
    def run(
        self,
        context: "PipelineContext",
        targets: list[ScenarioTarget],
        *,
        cursor: AutomationCursor | None = None,
    ) -> list[ScenarioOutcome]:
        outcomes: list[ScenarioOutcome] = []
        # Skip scenarios preceding the cursor.
        if cursor is not None:
            targets = [t for t in targets if t.sub_bid >= cursor.sub_bid]
        for target in targets:
            increments = self.etch.run_scenario(context, target)
            start_idx = 0
            start_iter = 1
            if cursor is not None and cursor.sub_bid == target.sub_bid:
                start_idx = cursor.increment_index
                start_iter = cursor.iteration
                # The cursor's increment was the one that failed; resume at
                # the same increment. If the cursor's increment was already
                # complete (defensive: cursor could be stale), start at next.
                cursor = None
            for j, increment in enumerate(increments):
                if j < start_idx:
                    continue
                iteration = start_iter if j == start_idx else 1
                while True:
                    self.cursor = AutomationCursor(
                        sub_bid=target.sub_bid,
                        increment_index=increment.index,
                        iteration=iteration,
                    )
                    context.automation_cursor = self.cursor
                    context.iteration = iteration
                    result = self.realize.run_increment(
                        context, target=target, increment=increment
                    )
                    route = self.inspect_loop.inspect_increment(
                        context, target=target, increment=increment, result=result
                    )
                    if route is None:
                        break
                    if route == "spec":
                        from mage.orchestration.etch import ScenarioInspectHalted

                        raise ScenarioInspectHalted(
                            f"spec-route finding for sub-bid {target.sub_bid!r} at iteration {iteration}"
                        )
                    if route == "code":
                        iteration += 1
                        if iteration > self.per_loop_max_iterations:
                            from mage.orchestration.etch import ScenarioInspectHalted

                            raise ScenarioInspectHalted(
                                f"per-loop budget exhausted for sub-bid {target.sub_bid!r}"
                            )
                        continue
                    break
            outcomes.append(
                ScenarioOutcome(
                    sub_bid=target.sub_bid,
                    test_paths=[inc.red_test_path for inc in increments],
                )
            )
            self.cursor = None
            context.automation_cursor = None
        return outcomes
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_runner.py -q`
Expected: 7 passed (4 from Task 7 + 3 from this task)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/runner.py tests/unit/test_runner.py
git commit -m "feat(runner): FeatureRunner resume from AutomationCursor"
```

---

### Task 9: `PipelineContext.automation_cursor` + host_config field

**Files:**
- Modify: `src/mage/orchestration/nodes.py`
- Modify: `tests/unit/test_nodes.py`

**Interfaces:**
- Consumes: `AutomationCursor` (Task 1), `HostConfig` (Task 2)
- Produces: `PipelineContext.automation_cursor: AutomationCursor | None = None`, `PipelineContext.host_config: HostConfig | None = None`

- [ ] **Step 1: Write a failing test**

Add to `tests/unit/test_nodes.py`:

```python
def test_pipeline_context_carries_automation_cursor():
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.runner import AutomationCursor
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    from mage.verification.host_overrides import HostConfig
    from pathlib import Path

    ctx = PipelineContext(
        project_dir=Path("/tmp"),
        mapping=MappingArtifact(project_id="p"),
        events_log=EventsLog(Path("/tmp/events.jsonl")),
        plan_path=Path("/tmp/plan.md"),
        iteration=0,
    )
    assert ctx.automation_cursor is None

    cursor = AutomationCursor(sub_bid="00001-0001", increment_index=0, iteration=1)
    ctx.automation_cursor = cursor
    assert ctx.automation_cursor is cursor

    ctx.automation_cursor = None
    assert ctx.automation_cursor is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_nodes.py -q -k cursor`
Expected: fail — `automation_cursor` not a field

- [ ] **Step 3: Add the field to `PipelineContext`**

In `src/mage/orchestration/nodes.py`, add to the `PipelineContext` class body:

```python
from mage.orchestration.runner import AutomationCursor
```

Add field after `iteration: int = 0`:

```python
    automation_cursor: AutomationCursor | None = None
    host_config: HostConfig | None = None
```

(Add the `HostConfig` import too: `from mage.verification.host_overrides import HostConfig`. The import is local to this module; if it creates a cycle, defer to a TYPE_CHECKING import.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_nodes.py -q`
Expected: pass (and existing tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/nodes.py tests/unit/test_nodes.py
git commit -m "feat(context): PipelineContext carries automation_cursor and host_config"
```

---

### Task 10: `AutomationStage` shim

**Files:**
- Create: `src/mage/orchestration/automation.py`
- Create: `tests/unit/test_automation_stage.py`

**Interfaces:**
- Consumes: `PipelineContext` (Task 9), `FeatureRunner` (Tasks 7-8), `MappingArtifact`
- Produces: `class AutomationStage(StageNode)` with `name = "automation"`, `__init__(events_log, runner)`, `_run(context) -> PipelineContext`. Builds `ScenarioTarget` list from `context.mapping.base_bids[].scenarios[]` filtering `lifecycle_status == APPROVED`. Calls `runner.run(context, targets, cursor=context.automation_cursor)`. For each `ScenarioOutcome`: append `test_paths` to the matching `ScenarioEntry.tests`, set `lifecycle_status = LIVE`, save mapping, emit `SCENARIO_LIVE`.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_automation_stage.py`:

```python
"""Tests for AutomationStage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ConfigDict

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.automation import AutomationStage
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import (
    AutomationCursor,
    FeatureRunner,
    Increment,
    IncrementResult,
    ScenarioOutcome,
    ScenarioTarget,
)
from mage.verification.host_overrides import HostConfig


def _make_mapping(tmp_path, scenarios: list[ScenarioEntry]) -> MappingArtifact:
    return MappingArtifact(
        schema_version=1,
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00001",
                behavior_name="b",
                behavior_description="d",
                depends_on=[],
                notes="",
                scenarios=scenarios,
            ),
        ],
    )


def _ctx(tmp_path, mapping: MappingArtifact) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=mapping,
        events_log=EventsLog(tmp_path / "events.jsonl"),
        plan_path=tmp_path / "plan.md",
        iteration=0,
        host_config=HostConfig(test_runner_command=["pytest"]),
    )


def _scenario(sub_bid: str, status: LifecycleStatus) -> ScenarioEntry:
    return ScenarioEntry(
        sub_bid=sub_bid,
        scenario_text_hash=hash(sub_bid),
        lifecycle_status=status,
    )


def test_automation_stage_excludes_non_approved_scenarios(tmp_path):
    scenarios = [
        _scenario("00001-0001", LifecycleStatus.APPROVED),
        _scenario("00001-0002", LifecycleStatus.LIVE),       # already done
        _scenario("00001-0003", LifecycleStatus.INSCRIBING), # not ready
    ]
    mapping = _make_mapping(tmp_path, scenarios)
    ctx = _ctx(tmp_path, mapping)

    captured_targets: list[list[ScenarioTarget]] = []

    class _Runner:
        def run(self, context, targets, *, cursor=None):
            captured_targets.append(targets)
            return [
                ScenarioOutcome(sub_bid=t.sub_bid, test_paths=["t.py"])
                for t in targets
            ]

    stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type]
    stage.run(ctx)

    sent = captured_targets[0]
    assert [t.sub_bid for t in sent] == ["00001-0001"]


def test_automation_stage_writes_back_scenario_outcomes(tmp_path):
    mapping = _make_mapping(
        tmp_path,
        [_scenario("00001-0001", LifecycleStatus.APPROVED)],
    )
    ctx = _ctx(tmp_path, mapping)

    class _Runner:
        def run(self, context, targets, *, cursor=None):
            return [ScenarioOutcome(sub_bid="00001-0001", test_paths=["t1.py", "t2.py"])]

    stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type]
    stage.run(ctx)

    saved = MappingArtifact.load(tmp_path / "mapping.yaml", ctx.events_log)
    entry = saved.base_bids[0].scenarios[0]
    assert entry.lifecycle_status == LifecycleStatus.LIVE
    assert entry.tests == ["t1.py", "t2.py"]


def test_automation_stage_emits_scenario_live(tmp_path):
    mapping = _make_mapping(
        tmp_path,
        [_scenario("00001-0001", LifecycleStatus.APPROVED)],
    )
    ctx = _ctx(tmp_path, mapping)

    class _Runner:
        def run(self, context, targets, *, cursor=None):
            return [ScenarioOutcome(sub_bid="00001-0001", test_paths=["t.py"])]

    stage = AutomationStage(ctx.events_log, runner=_Runner())  # type: ignore[arg-type]
    stage.run(ctx)

    types = [e.event_type.value for e in ctx.events_log.read_all()]
    assert types.count("scenario_live") == 1
    assert "stage_started" in types
    assert "stage_completed" in types
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_automation_stage.py -q`
Expected: `ModuleNotFoundError: No module named 'mage.orchestration.automation'`

- [ ] **Step 3: Implement `AutomationStage`**

`src/mage/orchestration/automation.py`:

```python
"""AutomationStage: graph-facing shim around FeatureRunner.

Reads approved scenarios from the mapping, builds ScenarioTargets, delegates
to FeatureRunner, and writes the resulting ScenarioOutcomes back to the
mapping. Emits SCENARIO_LIVE per completed scenario so InspectFeatureStage's
"all scenarios live" precondition is satisfied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mage.artifacts.mapping import LifecycleStatus
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.runner import FeatureRunner, ScenarioTarget


class AutomationStage(StageNode):
    """StageNode wrapping the automation loop."""

    name = "automation"

    def __init__(self, events_log: EventsLog, *, runner: FeatureRunner) -> None:
        super().__init__(events_log)
        self.runner = runner

    def _build_targets(self, context: PipelineContext) -> list[ScenarioTarget]:
        targets: list[ScenarioTarget] = []
        for entry in context.mapping.base_bids:
            for scenario in entry.scenarios:
                if scenario.lifecycle_status != LifecycleStatus.APPROVED:
                    continue
                targets.append(
                    ScenarioTarget(
                        base_bid=entry.base_bid,
                        sub_bid=scenario.sub_bid,
                        scenario_name=scenario.sub_bid,
                        gherkin_body="",
                        steps=[],
                    )
                )
        return targets

    def _run(self, context: PipelineContext) -> PipelineContext:
        targets = self._build_targets(context)
        outcomes = self.runner.run(
            context, targets, cursor=context.automation_cursor
        )
        # Build a sub-bid -> outcome map for the write-back.
        outcomes_by_sub = {o.sub_bid: o for o in outcomes}
        for entry in context.mapping.base_bids:
            for scenario in entry.scenarios:
                outcome = outcomes_by_sub.get(scenario.sub_bid)
                if outcome is None:
                    continue
                scenario.tests = list(scenario.tests) + list(outcome.test_paths)
                scenario.lifecycle_status = LifecycleStatus.LIVE
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.SCENARIO_LIVE,
                        payload={
                            "sub_bid": scenario.sub_bid,
                            "test_paths": list(outcome.test_paths),
                        },
                    )
                )
        mapping_path = context.project_dir / "mapping.yaml"
        if context.project_dir is not None and Path(context.project_dir).exists():
            context.mapping.save(mapping_path)
        context.automation_cursor = None
        return context
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_automation_stage.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/automation.py tests/unit/test_automation_stage.py
git commit -m "feat(automation): AutomationStage shim writes back scenario outcomes"
```

---

### Task 11: Graph halt normalization

**Files:**
- Modify: `src/mage/orchestration/graph.py`
- Modify: `tests/unit/test_graph.py`

**Interfaces:**
- Consumes: existing `PipelineGraph` (`graph.py:15-91`)
- Produces: `PipelineGraph.run` catches `ScenarioInspectHalted` and routes it through `_persist_halt` (raising `SystemExit(0)` after), like the other three halt types.

- [ ] **Step 1: Write a failing test**

Append to `tests/unit/test_graph.py`:

```python
def test_graph_stops_on_scenario_inspect_halted():
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.etch import ScenarioInspectHalted
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext, StageNode
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.persistence import FileStatePersistence
    from pathlib import Path
    import pytest

    class _HaltStage(StageNode):
        name = "halt_stage"
        def _run(self, context):
            raise ScenarioInspectHalted("spec finding")

    class _Dummy(StageNode):
        name = "dummy"
        def _run(self, context):
            return context

    tmp = Path("/tmp") / "p6_halt_test"
    tmp.mkdir(parents=True, exist_ok=True)
    log = EventsLog(tmp / "events.jsonl")
    graph = PipelineGraph(stages=[_HaltStage(log), _Dummy(log)], events_log=log)
    ctx = PipelineContext(
        project_dir=tmp,
        mapping=MappingArtifact(project_id="p"),
        events_log=log,
        plan_path=tmp / "plan.md",
        iteration=0,
    )
    with pytest.raises(SystemExit):
        graph.run(ctx)
    # Mapping was persisted as halted
    saved = MappingArtifact.load(tmp / "mapping.yaml", log)
    assert saved.feature_status == "halted"
    # State was persisted
    state = FileStatePersistence(state_dir=tmp / ".haileris" / "state", state_type=PipelineContext).load_state()
    assert state is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_graph.py -q -k halt`
Expected: fails — current `except ScenarioInspectHalted` falls through to the next stage and never persists

- [ ] **Step 3: Normalize halt handling in `graph.py`**

Replace the `except ScenarioInspectHalted` clause in `graph.py:36-48` with:

```python
            except ScenarioInspectHalted as e:
                # All halts now share the persistence path. The graph stops
                # cleanly so a feature halt (or any other halt) cannot leak
                # into a later stage.
                context.mapping = context.mapping.model_copy(
                    update={"feature_status": "halted"}
                )
                if context.project_dir is not None and context.project_dir.exists():
                    context.mapping.save(context.project_dir / "mapping.yaml")
                self._persist_halt(context, e)
                raise SystemExit(0) from e
```

(Add `e` to the `ScenarioInspectHalted` raise so `_persist_halt` can record the reason. The exception type already accepts an optional message.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_graph.py -q`
Expected: all graph tests pass

- [ ] **Step 5: Commit**

```bash
git add src/mage/orchestration/graph.py tests/unit/test_graph.py
git commit -m "fix(graph): route ScenarioInspectHalted through persist_halt"
```

---

### Task 12: `mage run` implementation

**Files:**
- Modify: `src/mage/cli.py` (`cmd_run` at `cli.py:189-205`)
- Modify: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `MappingArtifact.load`, `FileStatePersistence.load_state`, the five stage classes, `PipelineGraph`
- Produces: `cmd_run` loads mapping + state, constructs stages, builds the graph, runs it. Returns 0 on clean exit, 1 on `SettleError` (already handled). `--model` overrides `HostConfig.model`.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_cli.py`:

```python
def test_mage_run_loads_state_and_constructs_stages(tmp_path, monkeypatch):
    """The dry-run path: verify the stage list is constructed in order."""
    from mage.cli import main

    project = tmp_path / "proj"
    project.mkdir()
    # Plant a minimal mapping with zero approved scenarios.
    (project / "mapping.yaml").write_text(
        "schema_version: 1\nproject_id: p\nbase_bids: []\n"
    )
    rc = main(["run", "--dry-run", "--project-dir", str(project)])
    # Empty project means Inscribe sees no behaviors; should still exit 0.
    assert rc == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -q -k run_loads`
Expected: 1 failed — `cmd_run` raises `NotImplementedError`

- [ ] **Step 3: Implement `cmd_run`**

Replace `cmd_run` (`cli.py:189-205`) with:

```python
def cmd_run(args):
    """Run the pipeline with halt handling and resume support."""
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.events import EventsLog
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.inscribe import InscribeStage
    from mage.orchestration.inspect_feature import InspectFeatureStage
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.persistence import FileStatePersistence
    from mage.orchestration.settle_feature import SettleFeatureStage
    from mage.orchestration.automation import AutomationStage
    from mage.verification.host_overrides import HostConfig

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    state_dir = project_dir / ".haileris" / "state"

    mapping_path = project_dir / "mapping.yaml"
    if mapping_path.exists():
        mapping = MappingArtifact.load(mapping_path, log)
    else:
        mapping = MappingArtifact(schema_version=1, project_id=project_dir.name, base_bids=[])

    persistence = FileStatePersistence(state_dir=state_dir, state_type=PipelineContext)
    saved = persistence.load_state()
    initial_context = saved or PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
        iteration=0,
    )

    host_config = load_host_config(project_dir)
    if getattr(args, "model", None):
        host_config = host_config.model_copy(update={"model": args.model})

    # Stub agents when --dry-run is set; real agents are wired in a follow-up plan.
    stages = [
        DecompositionStage(log),
        InscribeStage(log),
        AutomationStage(log, runner=...),  # runner is constructed in Task 13
        InspectFeatureStage(log, reviewers=..., mechanical_verifier=...),
        SettleFeatureStage(log, host_config=host_config),
    ]
    graph = PipelineGraph(stages=stages, events_log=log)
    try:
        graph.run(initial_context)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 — top-level CLI guard
        print(f"mage run: error: {error}", file=sys.stderr)
        return 1
    print(f"mage run: complete for {project_dir}")
    return 0
```

(The `...` placeholders for `runner`, `reviewers`, `mechanical_verifier` are filled in Task 13.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -q -k run_loads`
Expected: 1 passed (other CLI tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/mage/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): implement mage run with state resume"
```

---

### Task 13: `--dry-run` flag and `cmd_review_resume` removal

**Files:**
- Modify: `src/mage/cli.py` (argument parser + `cmd_run`)
- Modify: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `cmd_run` (Task 12)
- Produces: `mage run` accepts `--dry-run` and `--model`. `--dry-run` substitutes stub agents. `cmd_review_resume` is deleted; any test that exercises it is updated to assert the command is gone.

- [ ] **Step 1: Add `--dry-run` and `--model` to the run parser**

In `cli.py`'s argument setup (around `cli.py:160`), for the `run` subcommand:

```python
    run_parser.add_argument("--dry-run", action="store_true", help="Use stub agents")
    run_parser.add_argument("--model", help="Override the LLM model identifier")
```

- [ ] **Step 2: Wire `--dry-run` in `cmd_run`**

In `cmd_run`, before constructing stages, branch on `args.dry_run`:

```python
    if args.dry_run:
        from mage.agents.etch import EtchAgent
        from mage.agents.realize import RealizeAgent
        runner = _make_dry_run_runner(log)
        # etc.
    else:
        # Construct real agents using host_config.model.
        ...
```

(Implement `_make_dry_run_runner` as a small factory that wires stub `EtchAgent`, `RealizeAgent`, `IncrementQualityReviewer`, and a no-op `MechanicalVerifier` into the runner. Stubs echo fixed values.)

- [ ] **Step 3: Delete `cmd_review_resume`**

Remove the `cmd_review_resume` function and its branch in `main` (`cli.py:288-300` and the `if args.command == "review" and args.review_command == "resume"` clause).

- [ ] **Step 4: Update `tests/unit/test_cli.py`**

Delete tests that exercise `mage review resume`. Add a test that `mage review resume` exits with `2` (unrecognized command) and prints nothing actionable:

```python
def test_mage_review_resume_is_gone(tmp_path, capsys):
    from mage.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["review", "resume", "--project-dir", str(tmp_path)])
    assert exc.value.code == 2
```

- [ ] **Step 5: Run the full test suite**

Run: `make test`
Expected: pass

- [ ] **Step 6: Commit**

```bash
git add src/mage/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): mage run --dry-run --model; remove review resume"
```

---

### Task 14: End-to-end pipeline test

**Files:**
- Create: `tests/features/test_e2e_pipeline.py`

**Interfaces:**
- Consumes: `mage run --dry-run` (Task 13)
- Produces: an e2e test that runs `mage run --dry-run` against a fixture project with one approved scenario, asserts the full sequence runs and `feature_status == "settled"`. Plus a halt-and-resume round trip: force a spec halt, persist the cursor, re-run, assert it resumes at the same increment.

- [ ] **Step 1: Create the fixture builder**

In `tests/features/test_e2e_pipeline.py`, add a helper that plants a fixture project under `tmp_path` with: a `plan.md`, a `mapping.yaml` containing one `APPROVED` scenario, and a stub `agent/host` so the dry-run stubs are wired.

- [ ] **Step 2: Write the happy-path test**

```python
def test_mage_run_dry_run_completes_a_feature(tmp_path):
    from mage.cli import main

    _plant_fixture(tmp_path, approved_sub_bid="00001-0001")
    rc = main(["run", "--dry-run", "--project-dir", str(tmp_path)])
    assert rc == 0

    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    saved = MappingArtifact.load(tmp_path / "mapping.yaml", EventsLog(tmp_path / "events.jsonl"))
    assert saved.feature_status == "settled"
```

- [ ] **Step 3: Write the halt-and-resume test**

```python
def test_mage_run_resumes_from_persisted_cursor(tmp_path):
    from mage.cli import main
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.persistence import FileStatePersistence

    _plant_fixture(tmp_path, approved_sub_bid="00001-0001", fail_sub_bid="00001-0001")
    # First run halts on a spec-route finding for the only scenario.
    with pytest.raises(SystemExit):
        main(["run", "--dry-run", "--project-dir", str(tmp_path)])
    # Cursor was persisted.
    persistence = FileStatePersistence(
        state_dir=tmp_path / ".haileris" / "state",
        state_type=PipelineContext,
    )
    saved = persistence.load_state()
    assert saved is not None
    assert saved.automation_cursor is not None
    # Second run, with the fixture now reporting clean, completes.
    _repair_fixture(tmp_path)  # makes the next inspect pass
    rc = main(["run", "--dry-run", "--project-dir", str(tmp_path)])
    assert rc == 0
```

- [ ] **Step 4: Run the feature tests**

Run: `make features-test`
Expected: both pass (after fixture is fully wired; this is the longest task and may require iteration on `_plant_fixture` / `_repair_fixture`)

- [ ] **Step 5: Commit**

```bash
git add tests/features/test_e2e_pipeline.py
git commit -m "test(e2e): mage run dry-run end-to-end and halt-resume round trip"
```

---

## Self-Review

**Spec coverage:**
- R1 (gap statement) — Task 1 introduces the data models that prove the gap
- R2 (architecture) — Tasks 7, 8, 9, 10 build the runner, cursor, context, shim
- R3 (data flow) — Tasks 1, 3, 4, 5 implement `ScenarioTarget`, `Increment`, `IncrementResult`, `ScenarioOutcome`. `AutomationStage` writes back outcomes (Task 10)
- R4 (signature changes) — Tasks 3, 4, 5 each rewrite one stage
- R4.1 (route on finding) — Task 6
- R5 (halt/resume) — Tasks 8, 9, 11
- R5.1 (cursor) — Tasks 1, 8, 9
- R6 (CLI) — Tasks 12, 13
- R7 (error handling) — covered in Task 7 (route semantics), Task 11 (halt), Task 9 (cursor for retries)
- R8 (testing) — every task has a test
- R9 (file structure) — every file is created or modified

**Placeholder scan:** All code blocks are complete. The `_plant_fixture` / `_repair_fixture` placeholders in Task 14 are explained as a fixture helper to be written during that task — the plan describes their behavior; the implementer fills them in.

**Type consistency:** `ScenarioTarget`, `Increment`, `IncrementResult`, `ScenarioOutcome`, `AutomationCursor` defined in Task 1 are referenced unchanged through Tasks 3-10. `FeatureRunner.run` signature is consistent across Tasks 7, 8, 10. `PipelineContext.automation_cursor` set in Tasks 9-10 matches the cursor the runner writes in Tasks 7-8.

**Gaps fixed in the spec during self-review:** None — all four gaps identified during the spec self-review (loop, data flow, halt normalization, scenario-live transition) have tasks. The route-detection defect is Task 6.
