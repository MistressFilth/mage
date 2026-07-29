# Pipeline Wiring Design (Plan 6)

**Date:** 2026-07-28
**Status:** Approved
**Supersedes scope of:** the "Plan 6 (Three Practices + Concurrency Enforcement)" placeholder referenced throughout Plans 1–5

## Goal

Make `mage run` execute a feature end to end: Decomposition → Inscribe →
Automation (Etch → Realize → InspectLoop, nested) → InspectFeature → Settle.
Done means an end-to-end run completes on stub agents, with halt-and-resume
working across the automation loop.

Plans 1–5 built and reviewed every stage in isolation. None of them has ever
run in sequence, because `mage run` raises `NotImplementedError`
(`cli.py:205`) and no code constructs the stage list.

## Scope decision

"Plan 6" accumulated every deferral from Plans 1–5. That backlog is three
independent subsystems plus a stub-completion pile, and it is decomposed as:

| Plan | Content |
|---|---|
| **6 (this spec)** | Pipeline wiring: the runner, the loop, halt/resume, `mage run` |
| 7 | Three Practices discipline: forward-only ordering, recurrence and reversion rules |
| 8 | Concurrency: parallel reviewer dispatch, parallel scenario processing, mapping write safety |
| 9 | Stub completion: `EtchAgent` LLM wiring, deferred-tool pause, mechanical pre-check wiring, review-meta-aggregator |

Wiring comes first because ordering discipline cannot be enforced across
stages that never run together, and a pipeline with no runner cannot be
parallelized.

## R1. The gap

The wiring problem is larger than assembling a stage list. Three defects in
the inner loop, each verifiable in the current source:

**No loop exists.** `RealizeStage._run_single_increment` and
`InspectLoopStage._run_single_increment` each run exactly one increment and
return `None`. Nothing iterates them. The budget check at
`inspect_loop.py:170` (`iteration > self.host_config.per_loop_max_iterations`)
reads `context.iteration`, which no caller advances.

**Ownership is circular and unimplemented.** `realize.py:53` documents Realize
as "Called by InspectLoopStage (Task 12)". `inspect_loop.py:92-95` documents
InspectLoop's entry point as one "which the RealizeStage (or external driver)
calls per increment". Neither calls the other. `InspectLoopStage.__init__`
accepts `realize_stage` (`inspect_loop.py:82`), stores it (`:88`), and never
reads it.

**No data flows between the three stages.** `RealizeStage._run_single_increment`
calls `self.agent.run(...)` and discards the result, so
`RealizeOutput.files_changed` and `.summary` reach nobody.
`InspectLoopStage._run_single_increment` requires `increment_diff`, `new_test`,
and `scenario_steps` as keyword arguments that no producer supplies.
`EtchStage._run` hardcodes `scenario_name="stub"` and `increment_index=0`,
labelled in-source as a "test fixture only" stub.

There is no Ascertain stage; `parse_ascertain` (`artifacts/ascertain.py:54`)
reads a human-authored file. Ascertain is an input artifact, not a pipeline
stage, and the runner does not invoke it.

**No scenario ever becomes live.** `EventType.SCENARIO_LIVE`
(`events.py:66`) is defined and never emitted. `LifecycleStatus.LIVE`
(`mapping.py:26`) is defined and never assigned — `InscribeStage` sets
`APPROVED` (`inscribe.py:252`) and nothing advances it. Since
`InspectFeatureStage` is specified to run "once per feature after all
scenarios are `live`", it could never legitimately fire. Plan 6 owns the
`APPROVED → LIVE` transition and the `SCENARIO_LIVE` emission, because the
automation loop is what completes a scenario.

`ScenarioEntry.tests` (`mapping.py:59`) is likewise always empty; Etch
produces the red-test paths that belong in it.

## R2. Architecture — graph shim plus loop driver

`PipelineGraph` keeps the coarse sequence and its existing halt handling:

```
Decomposition → Inscribe → AutomationStage → InspectFeatureStage → SettleFeatureStage
```

`AutomationStage` (new, `orchestration/automation.py`) is a thin `StageNode`.
Its `_run` reads approved scenarios from `context.mapping`, builds
`ScenarioTarget`s, delegates to `FeatureRunner`, and applies the resulting
mapping writes. It exists so the nesting sits behind the `StageNode` contract
the graph already understands, and so a halt raised inside the nesting
propagates through the graph's existing `except` clauses without new
machinery.

`FeatureRunner` (new, `orchestration/runner.py`) owns both loops and nothing
else. It calls no agents directly, emits no events of its own, and performs no
artifact writes — it mutates `context.automation_cursor` in memory and returns
a `ScenarioOutcome` per completed scenario for `AutomationStage` to persist:

```python
def run(self, context, targets, *, cursor=None) -> list[ScenarioOutcome]:
    outcomes = []
    for target in self._remaining(targets, cursor):     # outer loop
        increments = self.etch.run_scenario(context, target)
        for increment in increments[self._start_index(target, cursor):]:
            iteration = self._start_iteration(target, increment, cursor)
            while True:                                  # inner loop
                context.automation_cursor = AutomationCursor(
                    sub_bid=target.sub_bid,
                    increment_index=increment.index,
                    iteration=iteration,
                )
                context.iteration = iteration
                result = self.realize.run_increment(
                    context, target=target, increment=increment
                )
                route = self.inspect_loop.inspect_increment(
                    context, target=target, increment=increment, result=result
                )
                if route is None:
                    break                                # clean, or cosmetic-only
                if route == "spec":
                    raise ScenarioInspectHalted(
                        sub_bid=target.sub_bid, iteration=iteration
                    )
                iteration += 1                           # route == "code": re-loop
        outcomes.append(
            ScenarioOutcome(
                sub_bid=target.sub_bid,
                test_paths=[inc.red_test_path for inc in increments],
            )
        )
        context.automation_cursor = None
    return outcomes
```

Carry-forward is not a runner concern: `RealizeStage.run_increment` already
pulls the last `per_scenario_window` journal entries for the sub-BID and the
last `cross_scenario_window` entries from siblings (`realize.py:62-77`). The
runner passes only the target and the increment.

The three route values come from Plan 4's R20 routing. `FeatureRunner` reads
them; it does not re-derive them.

**Why this shape.** Two alternatives were considered. Full pydantic-graph
`BaseNode` traversal (what Plan 1's comments promised) would rewrite every
stage and push the loop variables into graph state, turning legible nesting
into a state machine spread across seven files — to buy state persistence the
project already has in `FileStatePersistence`. Replacing `PipelineGraph`
outright with a single driver would discard working, reviewed halt handling.
The hybrid changes only what is broken.

## R3. Data flow

Four frozen models in `orchestration/runner.py` carry state between stages.
They exist because the current signatures pass loose `str` keyword arguments
that no producer fills.

```python
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
```

`ScenarioTarget` is built by `AutomationStage` from
`context.mapping.base_bids[].scenarios[]`, filtered to
`lifecycle_status == LifecycleStatus.APPROVED`. Entries already at `LIVE` are
excluded, so a crash mid-feature naturally resumes at the first unfinished
scenario; the cursor resolves position only *within* a scenario. Ordering is
`base_bids` list order, then `scenarios` list order within each — both are
append-ordered by Decomposition and Inscribe respectively, so this is source
order. That is the only place mapping structure is read; `FeatureRunner` never
touches the mapping.

For each `ScenarioOutcome`, `AutomationStage` sets the entry's
`lifecycle_status` to `LifecycleStatus.LIVE`, appends `test_paths` to
`ScenarioEntry.tests`, saves the mapping, and emits `SCENARIO_LIVE`. This is
the transition identified as missing in R1; `InspectFeatureStage`'s "all
scenarios live" precondition depends on it.

`IncrementResult.diff` is the one field with no existing source.
`RealizeAgent.run()` returns `RealizeOutput(files_changed, summary)` — no diff
— but `InspectLoopStage` needs `increment_diff` to hand the reviewer.
`RealizeStage` gains an injected `command_runner` matching the
`CommandRunner` pattern `SettleFeatureStage` already uses
(`settle_feature.py:17`), and computes the diff as
`git diff --unified=10 -- <files_changed>` after the agent runs. Injected, so
tests substitute a recording fake and never shell out.

## R4. Signature changes to existing stages

`EtchStage`, `RealizeStage`, and `InspectLoopStage` stop subclassing
`StageNode`. Their `_run(context) -> context` implementations are either stubs
or `raise NotImplementedError`; the contract was never right for stages that
need a loop variable, and keeping it forces the two dead methods to stay. Each
keeps emitting its own domain events (`ETCH_STARTED`,
`REALIZE_INCREMENT_DONE`, `INSPECT_LOOP_STARTED`), which is what the journal
and the existing e2e tests assert on. `AutomationStage` becomes the sole
`StageNode` in this layer, so `STAGE_STARTED` / `STAGE_COMPLETED` bracket the
automation phase exactly once.

| Before | After |
|---|---|
| `EtchStage._run(context)` — hardcodes `scenario_name="stub"` | `EtchStage.run_scenario(context, target) -> list[Increment]` |
| `RealizeStage._run_single_increment(...) -> None` | `RealizeStage.run_increment(context, *, target, increment, carry_forward) -> IncrementResult` |
| `InspectLoopStage._run_single_increment(...) -> None` | `InspectLoopStage.inspect_increment(context, *, target, increment, result) -> InspectRoute \| None` |
| `InspectLoopStage.__init__(..., realize_stage=None)` | parameter deleted |

Returning the route is the change that makes the loop possible: today the
routing decision is computed at `inspect_loop.py:211-222`, written to the
journal, and discarded.

### R4.1. Route detection defect (pre-existing, must be fixed here)

Route detection at `inspect_loop.py:213-222` reads `getattr(f, "route", None)`,
falls back to parsing `f.suggestion` for a `"spec:"` or `"cosmetic:"` prefix,
and otherwise defaults to `"code"`. `ReviewerFinding` has no `route` field, so
against a real reviewer every finding routes by string prefix or silently
becomes `"code"` — a Critical spec finding would loop as a code fix instead of
halting.

This was flagged during Plan 4 Task 8 and deferred. Plan 6 must fix it,
because Plan 6 is where the route value first controls anything: add
`route: InspectRoute` to the reviewer finding schema, have
`IncrementQualityReviewer` populate it, and delete the prefix-parsing
fallback.

## R5. Halt and resume

Four halt exceptions exist. Wiring them into one runner exposes an
inconsistency that has never mattered because nothing ran in sequence:

| Exception | Raised by | Graph today (`graph.py:36-67`) |
|---|---|---|
| `ScenarioInspectHalted` | InspectLoop, spec route | sets `feature_status="inspect_pending"`, saves mapping, **falls through to the next stage** |
| `InspectFeatureHalted` | InspectFeature, eof budget | sets `feature_status="halted"`, `SystemExit(0)` |
| `ReviewBudgetExhausted` | Inscribe | `SystemExit(0)`, no state persisted |
| `PlanRevisionRequired` | Decomposition / Plan | `_persist_halt` writes event + context, `SystemExit(0)` |

`ScenarioInspectHalted` is the defect. It is the only halt that does not stop
the graph, so once `AutomationStage` joins the sequence, a scenario halting on
a spec-route finding lets `InspectFeatureStage` and `SettleFeatureStage` run
against a feature whose scenarios are not all live — and Settle would then
gate on an `InspectArtifact` built from an incomplete feature. Plan 6 changes
that clause to `SystemExit(0)` after persisting, matching the other three. The
comment at `graph.py:37-40` ("update in-memory mapping so subsequent stages
observe the status") documents an intent that no longer applies once there is
a real sequence.

`ReviewBudgetExhausted` also stops without persisting, so a resume has nothing
to load. Plan 6 routes all four halts through `_persist_halt`, which already
writes both the event and the `PipelineContext` snapshot. That settles the
question Plan 3 deferred: `ReviewBudgetExhausted` stays a distinct exception
type, it just shares the persistence path.

### R5.1. Cursor

`FileStatePersistence` already persists a `PipelineContext` to
`.haileris/state/pipeline-state.yaml` atomically. `PipelineContext` gains one
optional field:

```python
class AutomationCursor(BaseModel):
    model_config = ConfigDict(frozen=True)

    sub_bid: str          # scenario in progress
    increment_index: int  # increment in progress
    iteration: int        # inner-loop attempt for that increment
```

```python
automation_cursor: AutomationCursor | None = None
```

`FeatureRunner` writes the cursor to the context before each increment begins;
the graph's halt handlers persist it as part of the snapshot they already
write. On resume, `AutomationStage` skips scenarios preceding the cursor's
sub-BID and hands `FeatureRunner` the cursor as its starting position. A
cursor of `None` means start from the first approved scenario.

The cursor lives in `PipelineContext`, not `MappingArtifact`.
`MappingArtifact` is the durable project record — which scenarios exist, their
lifecycle status, the inspect journal. Loop position is runtime state, and
storing it in the mapping would rewrite the project artifact on every
increment.

## R6. CLI

`cmd_run` (`cli.py:189-205`) loses its `NotImplementedError`: load mapping,
load any persisted context, construct the five stages with their agents and
reviewers, build `PipelineGraph`, run. Resume is not a separate code path — if
`load_state()` returns a context, `mage run` continues from it; otherwise it
starts fresh. That is what `cmd_run` already gestures at with the unused
`halted_ctx` at `cli.py:203`.

`mage review resume` (`cli.py:288-300`) is deleted. It prints "full wiring
deferred to Plan 6" and exits; with `mage run` resuming automatically, a
second command that only reports readiness is a strictly worse way to do the
same thing. `mage plan revise` already tells the user "Restart the pipeline
with: mage run" (`cli.py:186`), and that instruction covers a review halt too.

`mage run` gains two options:

- `--model MODEL` — the model identifier handed to all four LLM agents.
  `HostConfig` has no model field today; Plan 6 adds `model: str | None = None`
  so a host project can pin one. Resolution order is `--model`, then
  `HostConfig.model`, then pydantic-ai's own default (environment-driven).
- `--dry-run` — substitutes stub agents for all four LLM agents, ignoring
  model resolution entirely. This is what makes the end-to-end test runnable
  without a model, and what makes "done" checkable.

## R7. Error handling

**Inner-loop exhaustion.** `per_loop_max_iterations` is 8
(`verification/host_overrides.py`). When the inner loop exceeds it,
`InspectLoopStage` already raises `ScenarioInspectHalted`
(`inspect_loop.py:170`). `FeatureRunner` does not re-implement the check; it
lets the exception through to `AutomationStage` and the graph.

**Route semantics in the loop.** `spec` halts. `code` re-loops with the
finding already in the carry-forward window. `cosmetic` is queued on
`mapping.feature_cosmetic_queue` by `InspectLoopStage` and does **not**
re-loop — a cosmetic finding must not consume a budget iteration, or a run
could exhaust its eight attempts on naming nits. When a pass yields only
cosmetic findings, `inspect_increment` returns `None`.

**Non-halt failures.** An agent raising, or `git diff` failing, is a crash,
not a halt. `FeatureRunner` does not catch these. The cursor was written
before the increment began, so persisted state points at the increment that
failed and `mage run` retries it. Swallowing these would silently skip work.

**Scenario isolation.** Plan 3's rule 1 is per-scenario independence, but
`ScenarioInspectHalted` stops the whole run. This is deliberate and unchanged:
independence governs the *approval* gate, not the automation loop. A halted
scenario means the spec is wrong, and automating siblings against a spec known
to be wrong produces work that gets thrown away.

## R8. Testing

| File | Coverage |
|---|---|
| `tests/unit/test_runner.py` (new) | `FeatureRunner` against fake stages returning scripted route sequences: clean first pass; `code` twice then clean; `cosmetic` does not advance the iteration counter; `spec` propagates `ScenarioInspectHalted`; cursor advances per increment; resume from a mid-scenario cursor skips completed scenarios |
| `tests/unit/test_automation_stage.py` (new) | `ScenarioTarget` construction from a `MappingArtifact`, including exclusion of non-`APPROVED` scenarios; `ScenarioOutcome` write-back sets `LIVE`, appends `tests`, saves the mapping, emits `SCENARIO_LIVE` |
| `tests/unit/test_realize_stage.py` (extend) | diff computation via a recording fake `command_runner` |
| `tests/unit/test_inspect_loop.py` (extend) | `inspect_increment` returns the route; `route` read from the finding field, no prefix parsing |
| `tests/unit/test_graph.py` (extend) | `ScenarioInspectHalted` now stops the graph; all four halts persist state |
| `tests/unit/test_cli.py` (extend) | `mage run --dry-run` constructs stages; `mage review resume` is gone |
| `tests/features/test_e2e_pipeline.py` (new) | `mage run --dry-run` on a fixture project from `plan.md` through Settle, asserting event order and `feature_status == "settled"`; plus a halt-and-resume round trip — force a spec halt mid-automation, assert `SystemExit(0)` and a persisted cursor, re-run, assert it resumes at the same increment rather than restarting |

## R9. File structure

| Path | Change |
|---|---|
| `src/mage/orchestration/runner.py` | new — `FeatureRunner`, `ScenarioTarget`, `Increment`, `IncrementResult`, `ScenarioOutcome`, `AutomationCursor` |
| `src/mage/orchestration/automation.py` | new — `AutomationStage`; owns the `APPROVED → LIVE` transition and `SCENARIO_LIVE` |
| `src/mage/orchestration/etch.py` | `run_scenario`; drop `StageNode` |
| `src/mage/orchestration/realize.py` | `run_increment` returning `IncrementResult`; injected `command_runner`; drop `StageNode` |
| `src/mage/orchestration/inspect_loop.py` | `inspect_increment` returning a route; drop `realize_stage`; drop `StageNode` |
| `src/mage/orchestration/graph.py` | `ScenarioInspectHalted` stops the graph; all halts persist |
| `src/mage/orchestration/nodes.py` | `PipelineContext.automation_cursor` |
| `src/mage/verification/host_overrides.py` | `HostConfig.model` |
| `src/mage/verification/reviewers/` | `route` on the finding schema; `IncrementQualityReviewer` populates it; delete prefix parsing |
| `src/mage/cli.py` | `cmd_run` implemented; `--model` and `--dry-run`; delete `cmd_review_resume` |

## Out of scope

- Three Practices ordering enforcement — Plan 7
- Concurrency of any kind; the loops are sequential — Plan 8
- `EtchAgent` LLM wiring, the `decomposition.py:98` deferred-tool pause, the
  Inscribe `MechanicalVerifier(checks=[])` wiring, the
  `inscribe.py:105` `existing_scenarios` placeholder, the
  `inscribe.py:300` per-behavior-vs-per-scenario halt — Plan 9
- The inert review-meta-aggregator — Plan 9
