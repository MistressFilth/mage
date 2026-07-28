# HAILERIS v2 — Etch + Realize + Inner TDD Loop, Inspect, Settle Design (Plans 4 + 5)

**Status:** DRAFT — initial brainstorming concluded 2026-07-28. Resolved decisions integrated. Awaiting user review and writing-plans transition.

**Plan 4 of 6 + Plan 5 of 6.** Builds on Plan 1 (Foundation), Plan 2 (Decomposition + Plan), Plan 3 (Inscribe + 7 Reviewers + Verdict Format). Plan 4 ships the per-scenario inner TDD cycle (Etch → Realize → per-loop Inspect). Plan 5 ships the end-of-feature Inspect (full sweep + 3-tier severity routing + fix wave) and Settle (cosmetic queue + finishing-equivalent).

## Vision

Build the inner TDD loop (Plan 4) and the end-of-feature Inspect + Settle pair (Plan 5) of the HAILERIS v2 pipeline. The **per-scenario inner cycle** runs `Etch → Realize → Inspect-loop` for each approved scenario from Plan 3, using mechanical pre-checks + one lightweight LLM reviewer (per-increment) with carry-forward into the next increment's prompt. The **end-of-feature pipeline** runs `Inspect-feature → Settle-feature` across the full feature: a digest-pinned InspectArtifact, 3-tier severity routing, an Inspect-feature-level fix-wave subagent, a cosmetic queue for natural-language minor items, and a `/finishing-a-development-branch`-equivalent finalization (verify tests, detect environment, 4-option menu, clean up).

The two-level Inspect mirrors `/subagent-driven-development`'s per-task + whole-branch review pattern; the local carry-forward mechanism mirrors its lesson-forward injection. Every concrete decision in this spec traces to one of nine structural resolutions (R18–R26, below) reached through a single brainstorming pass.

## Resolved Structural Decisions

These decisions are binding for Plans 4 + 5's implementation. They extend Plan 3's R11–R17 and the parent v2 design doc's pivots.

### R18. Two-level Inspect — per-loop + end-of-feature

The HAILERIS v2 pipeline has **two distinct Inspect stages** at different time-scales, mirroring `/subagent-driven-development`'s per-task review + whole-branch review pattern.

- **Per-loop Inspect (Plan 4)** runs after every Realize increment inside the per-scenario inner cycle. It is light, mechanical-first, and supports a single lightweight LLM reviewer. Its job is to validate the increment and feed findings into the next increment's prompt via carry-forward. It runs many times per scenario.
- **End-of-feature Inspect (Plan 5)** runs once after all scenarios are `live`. It is heavy, runs the full 7-reviewer sweep + an end-of-feature-only `CrossScenarioReviewer`, and produces the InspectArtifact that gates the feature for Settle. It runs once per feature.

**Why two levels, not one:** Per-loop Inspect catches increment-level issues (wrong abstraction, missed edge case in the new test, code smell introduced this increment) before they solidify into the codebase. End-of-feature Inspect catches cross-scenario issues (shared state leaks, ordering dependencies, integration gaps) that cannot be observed at per-scenario scope. Collapsing them would force one cadence to be either too tight or too loose.

**Why mirror `/subagent-driven-development`:** Per-task review and whole-branch review are different in scope and frequency; collapsing them weakens both. The same applies here.

### R19. Per-loop Inspect = mechanical-first + one lightweight LLM reviewer

The per-loop Inspect runs (in this order):

1. **Mechanical pre-check on the increment** (deterministic, no LLM):
   - `tests_pass` — **NEW check** (not in Plan 1's set). The new unit test asserts what Etch said it would; all tests in the relevant test scope are green.
   - `step_definitions_resolvable` — **REUSED from Plan 1**, but scoped to the increment's diff. Any new step definitions the increment introduces are resolvable.
   - `outer_still_green` — **NEW check**. The scenario's outer scenario-level test still passes (increments must not regress outer green).
   - `lifecycle_status_tag_current` — **EXTENDS Plan 1's `lifecycle-status-tag-present`**. The scenario's lifecycle tag (`@approved`, `@live`, etc.) matches the current `MappingArtifact.feature_status` value.
2. **`IncrementQualityReviewer`** (one lightweight Pydantic-AI reviewer, dimensional identity = `increment_quality`):
   - Reads: increment diff + new test + scenario's approved steps + recent carry-forward window (last 5 entries).
   - Produces: `ReviewerVerdict` with `ReviewerFinding`s tagged by the 3-route routing (R20).
   - Reviews code quality, test quality, and design appropriateness for the current increment — *not* spec/scenario clarity (those are end-of-feature concerns).
3. **Decision gate (R20 routing-driven)**:
   - Mechanical pre-check fails (any check) → log finding with `route="code"`, increment `iteration`, return to Realize. If `iteration >= per_loop_max_iterations`: raise `ScenarioInspectHalted`.
   - IncrementQualityReviewer produces zero findings OR all findings route=`cosmetic` → emit `INSPECT_LOOP_PASSED`; advance to next increment (or to outer-green check if this was the last).
   - IncrementQualityReviewer produces any finding route=`code` → log finding(s), emit `INSPECT_LOOP_PASSED` (increment still advances; finding is carry-forward into next Realize prompt). Iteration counter is **not** incremented on code-route findings (only on mechanical fails).
   - IncrementQualityReviewer produces any finding route=`spec` → emit `SCENARIO_HALT_PERSISTED` + raise `ScenarioInspectHalted` (spec-route is treated as halt-condition even within budget; per parent v2 design doc's "model cannot make spec changes during Realize" discipline).

The `increment_quality` dimension is part of the per-scenario Inspect-loop only. It is **not** registered in the end-of-feature Inspect's 7-reviewer sweep — end-of-feature has its own reviewer (`cross_scenario`, R22), making the per-loop and end-of-feature sweps distinct but consistent.

**Why one LLM reviewer, not seven:** Per-scenario inner cycle runs many times (every increment). 7 LLM calls per increment breaks the red→green→refactor cadence. The end-of-feature full sweep already covers the dimensions not exercised here.

**Why per-loop and not just mechanical:** Mechanical checks alone are CI gates, not real reviews. The "lesson-carry-forward" pattern from `/subagent-driven-development` requires a substantive LLM step that produces findings rich enough to be useful as prompt injection.

### R20. Per-loop Inspect 3-route routing inside Plan 4

`IncrementQualityReviewer.findings` are routed by their content (the implementer tags each finding with one of three routes during Reviewer-agent prompt construction, with the route also inferable from the finding's nature):

| Route | Target | What triggers |
|---|---|---|
| **spec** | Scenario halts; emit `SCENARIO_HALTED_FOR_REVISION`; queued for Inscribe reentry | "The approved spec for this scenario doesn't actually describe what this increment is doing" |
| **code** | Append to `inspect_journal`; inject into next Realize prompt (carry-forward) | "The increment's implementation has a problem the next increment needs to be aware of" |
| **cosmetic** | Append to `mapping.feature_cosmetic_queue` | "Natural-language text only; doesn't affect executable behavior" |

**Why three routes, not one:** Spec/code/cosmetic already exists for Inscribe's 7-reviewer routing (from Plan 3 + memory). The same discipline at per-loop scope keeps the model from making spec changes during Realize (a known anti-pattern from the parent v2 design). Cosmetic natural-language text can queue up; code-quality findings feed forward; spec problems halt cleanly.

**Spec route halts the scenario** rather than the whole feature. The halt is recoverable (Plan 2's resume mechanism + `mage run --resume`).

### R21. Carry-forward — local + injected recent window

Carry-forward state lives in two places:

1. **Durable:** `MappingArtifact.inspect_journal` — append-only list of `InspectJournalEntry` per sub-BID, persisted to `<project_dir>/mapping.yaml` (atomic write per append, parallel to `MappingArtifact.append_scenario` pattern from Plan 3).
2. **Injected:** A "recent window" (default: last 5 entries per scenario; last 3 cross-scenario entries) is injected into the next Realize's prompt at prompt-build time.

**What gets injected:** A compact markdown summary of recent findings, severity, location, route. Prompts in Plan 4's `RealizeAgent.run()` accept a `carry_forward: list[InspectJournalEntry]` parameter and fold it into the agent's system prompt section.

**Why local, not feature-global:** Feature-global accumulators produce noisy prompts the deeper the feature goes. Local gives per-scenario recency which is exactly what increment-level decisions need. Cross-scenario is a thin layer (last 3) to surface inter-scenario patterns without drowning prompts.

**Cross-process durability:** The journal is on disk via the mapping artifact's atomic write. Resume picks up where the scenario left off — the journal survives restarts, halt/resume cycles, and interruptions.

### R22. End-of-feature Inspect = full 7-reviewer sweep + CrossScenarioReviewer + 3-tier severity routing

Once all scenarios are `live`, `InspectFeatureStage` runs:

1. **Mechanical pre-check at feature level** — full mechanical set (not just the per-loop subset). All 7 Plan 1 checks.
2. **The 7 reviewer dimensions from Plan 3** — `spec_compliance`, `scenario_clarity`, `step_grammar`, `testability`, `determinism`, `naming_idiom`, `lifecycle_tags` — applied to the whole feature, not per scenario.
3. **`CrossScenarioReviewer` (NEW — end-of-feature-only, dimensional identity `cross_scenario`)** — looks for:
   - Shared state leaks across scenarios.
   - Ordering dependencies between scenarios that the scenario-level reviews don't observe.
   - Integration gaps (where two scenarios need to coordinate but don't).
   - Cross-scenario naming/tag collisions that surface only at the whole-feature level.
4. **3-tier severity routing (entire feature):**

| Severity | Route | Action |
|---|---|---|
| **Critical** | Reenter Realize | Affected scenarios (identified by `sub_bid`) re-enter the per-scenario Realize loop with the finding as carry-forward input. The cross-scenario element is recorded for the next Inspect-feature run. |
| **Important** | Fix-wave subagent | A single orchestrator subagent is dispatched with all Important findings; it applies targeted changes across the affected scenarios/code without reentering the per-scenario cycle. (Mirrors `/subagent-driven-development`'s final fix wave 1:1.) |
| **Minor** | Cosmetic queue | Appended to `MappingArtifact.feature_cosmetic_queue`. Settle-feature surfaces them. |

**Why 3-tier, not 1-tier or 2-tier:** Critical breaks the spec; Important is fixable cheaply without re-running cycles; Minor is natural-language noise. Conflating any of these either corrupts cycles with noise or hides problems in cosmetic queues.

**Scope of "affected scenarios" for Critical:** Cross-referenced from the finding's `citations` field (parallel to Inscribe's pattern from R14); falls back to "all scenarios that depend on the touched code path" if `citations` is empty.

### R23. Two distinct iteration budgets + two halt exceptions

`HostConfig` gains two new fields (mirroring `max_iterations` from Plan 3):

- `per_loop_max_iterations: int = 8` — per scenario. Shared by Realize and per-loop Inspect within the scenario's cycle.
- `eof_max_iterations: int = 3` — per feature. Consumed by Inspect-feature's fix-wave (after the first Inspect-feature pass surfaces findings, the fix-wave may be re-triggered up to `eof_max_iterations` total).

Two new exceptions, caught by `PipelineGraph` (parallel to `ReviewBudgetExhausted` from Plan 3):

- `ScenarioInspectHalted(base_bid: Base85BID, scenario_name: str, sub_bid: SubBIDLike, iteration: int)` — per-loop budget exhausted for one scenario. Feature continues with other scenarios.
- `InspectFeatureHalted(feature_id: str, iteration: int)` — end-of-feature budget exhausted. The feature halts; resume re-enters Inspect-feature.

### R24. InspectArtifact — digest-pinned, parallel to VerdictArtifact

`InspectArtifact` (in `src/mage/artifacts/inspect.py`) is the Plan 5 analog of `VerdictArtifact`. Same surface:

- `InspectArtifact.finalize(inspect_path, content, events_log)` — atomic write + SHA256 digest + `INSPECT_FEATURE_FINALIZED` event.
- `InspectArtifact.load(inspect_path, events_log)` — digest-verified read.
- `InspectArtifactDigestMismatchError` — raised if on-disk digest ≠ recorded.

**Content schema (`InspectArtifactContent`):**

```python
class InspectArtifactContent(BaseModel):
    model_config = ConfigDict(frozen=True)
    feature_id: str
    inspected_at: datetime
    iteration: int
    eof_max_iterations: int
    scenarios: list[ScenarioInspectStatus]  # live|needs_refactor|approved_with_caveat per sub_bid
    per_reviewer: list[ReviewerVerdict]   # full 7 + cross_scenario
    critical: list[ReviewerFinding]
    important: list[ReviewerFinding]
    minor: list[ReviewerFinding]
    cross_scenario: list[ReviewerFinding]
    ready_to_merge: bool
    ledger_markdown: str   # human-readable ledger table for the progress file
```

**Note:** The SHA256 digest is **not** a field on the content schema. Following Plan 2's `PlanArtifact` and Plan 3's `VerdictArtifact` convention, the digest is recorded as the event payload field `inspect_sha256` on the `INSPECT_FEATURE_FINALIZED` event and is the key returned by `InspectArtifact.finalize()`. The load() method recomputes and compares against the recorded value, raising `InspectArtifactDigestMismatchError` on mismatch.

**Storage path:** `<project_dir>/.haileris/inspect/<feature_id>/<iteration>.yaml` (iteration-keyed; revisions are new files, immutable history).

**Disposal / partial-failure semantics:**
- Scenarios already `live` remain `live` if a Critical finding halts Inspect-feature mid-pass.
- The InspectArtifact records the partial state at the most recent `INSPECT_FEATURE_FINALIZED`.
- Resume re-enters Inspect-feature, which loads the artifact and runs the next iteration's pass against the same scenarios + any newly fixed code.

### R25. Settle-feature = cosmetic queue handoff + finishing-equivalent

`SettleFeatureStage` runs once after `InspectFeatureStage` produces `ready_to_merge: true`. It has **two responsibilities in order** and explicitly **does not** do review (review is `InspectFeatureStage`'s job):

**Responsibility 1 — Cosmetic queue handoff:**
1. Aggregate per-scenario cosmetic queues (from R20's cosmetic route) + Inspect-feature's Minor findings into `MappingArtifact.feature_cosmetic_queue`.
2. Emit `SETTLE_COSMETIC_QUEUED` with `{feature_id, queue_size}`.
3. **No code changes are made by the model.** Spec / Important / Critical are not routed here — only natural-language cosmetic items. (This matches the parent v2 design doc's "Settle routing" discipline: model cannot make changes to live scenarios; only humans apply cosmetic changes; if a flagged cosmetic item is actually semantic on review, reclassify as spec → Inscribe reentry.)

**Responsibility 2 — Branch finalization (the `/finishing-a-development-branch` mirror):**
1. Verify tests pass on the full feature: `uv run pytest -v` (or the host-project's configured test command).
2. Detect environment (worktree vs main repo via `git rev-parse --git-dir` vs `git rev-parse --git-common-dir`, parallel to `/finishing-a-development-branch` Step 2).
3. Present the 4 standard options:
   - **Merge to base branch locally** — checkout base, merge, re-verify tests, delete feature branch.
   - **Push and create PR** — `git push -u origin <branch>`, create PR via `gh`.
   - **Keep as-is** — leave branch in place.
   - **Discard this work** — confirm, force-delete branch.
4. Execute the chosen option, including worktree cleanup for Options 1 + 4 (provenance check: only clean up `.worktrees/`-style worktrees, never harness-owned ones).
5. Emit `SETTLE_FEATURE_FINALIZED` with `{feature_id, disposition: "merged"|"pr_opened"|"kept"|"discarded"}`.

**Output:** `SettleReport` written to `<project_dir>/.haileris/settle/<feature_id>.md` — markdown summary of cosmetic queue + the chosen disposition + ledger entry for the progress file.

**Why Settle does not review:** Reviewer agents are bound to drafts and code artifacts. Settle is a presentation + handoff stage. Conflating Settle with Inspect-feature breaks the "model cannot make changes to live scenarios" discipline.

### R26. MappingArtifact extension + feature lifecycle status

`MappingArtifact` (from Plan 1, extended in Plans 2 + 3) gains the following for Plan 4 + 5:

**New fields:**
- `inspect_journal: dict[SubBIDKey, list[InspectJournalEntry]]` — per-scenario append-only journals for carry-forward.
- `feature_inspect: InspectArtifactRef | None` — digest-pinned reference to the most recent InspectArtifact.
- `feature_cosmetic_queue: list[CosmeticItem]` — natural-language cosmetic items for the human reviewer.
- `feature_status: Literal["pending", "live_assembling", "inspect_pending", "inspect_passed", "settled", "halted"]` — coarse state for resume + CLI surface.

**New methods:**
- `append_inspect_journal(sub_bid: SubBIDKey, entry: InspectJournalEntry) -> MappingArtifact` — append + atomic write. Returns new MappingArtifact (immutable update, parallel to `append_scenario`).
- `attach_feature_inspect(digest: str) -> MappingArtifact` — record reference.
- `append_cosmetic(item: CosmeticItem) -> MappingArtifact` — per-loop or eof cosmetic route.
- `feature_resume_state() -> InspectResumeState` — for resume picking up halted features.

**`InspectJournalEntry` schema:**

```python
class InspectJournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: datetime
    iteration: int
    dimension: str   # "mechanical" | "increment_quality" | "<reviewer_dimension>"
    severity: Literal["critical", "major", "minor"]
    route: Literal["spec", "code", "cosmetic"]   # only relevant for non-mechanical
    finding_id: str
    location: str
    issue: str
    rationale: str
```

## Architecture

### Module layout (Plan 4 + 5 additions)

```
src/mage/
├── artifacts/
│   ├── mapping.py              (Plan 1+2+3, extended: inspect_journal, feature_inspect, feature_cosmetic_queue, feature_status, append_* helpers)
│   ├── plan.py                 (Plan 2, unchanged)
│   ├── verdict.py              (Plan 3, unchanged)
│   └── inspect.py              (Plan 4+5 NEW — InspectArtifact + InspectArtifactContent + InspectJournalEntry schemas)
├── agents/
│   ├── decomposition.py        (Plan 2, unchanged)
│   ├── inscribe.py             (Plan 3, unchanged)
│   └── realize.py              (Plan 4 NEW — Etch + Realize agents with carry-forward prompt)
├── orchestration/
│   ├── decomposition.py        (Plan 2, unchanged)
│   ├── inscribe.py             (Plan 3, unchanged)
│   ├── etch.py                 (Plan 4 NEW — EtchStage)
│   ├── realize.py              (Plan 4 NEW — RealizeStage)
│   ├── inspect_loop.py         (Plan 4 NEW — InspectLoopStage)
│   ├── inspect_feature.py      (Plan 5 NEW — InspectFeatureStage)
│   └── settle_feature.py       (Plan 5 NEW — SettleFeatureStage)
├── verification/
│   ├── mechanical.py           (Plan 1, unchanged)
│   ├── host_overrides.py       (extended: per_loop_max_iterations, eof_max_iterations)
│   └── reviewers/
│       ├── base.py             (Plan 3, unchanged)
│       ├── spec_compliance.py  (Plan 3, unchanged)
│       ├── scenario_clarity.py (Plan 3, unchanged)
│       ├── step_grammar.py     (Plan 3, unchanged)
│       ├── testability.py      (Plan 3, unchanged)
│       ├── determinism.py      (Plan 3, unchanged)
│       ├── naming_idiom.py     (Plan 3, unchanged)
│       ├── lifecycle_tags.py   (Plan 3, unchanged)
│       └── increment_quality.py     (Plan 4 NEW — per-loop-only reviewer)
│       └── cross_scenario.py         (Plan 5 NEW — eof-only reviewer)
└── cli.py                      (extended: mage inspect show, mage settle run)
```

### `EtchStage` (orchestration, Plan 4)

A `StageNode` that runs **per scenario** during the inner TDD cycle. Position: after the scenario's `SCENARIO_APPROVED` event (Plan 3 gate). Inputs: `PipelineContext` with the scenario's `sub_bid`, behavior spec, approved steps, and the scenario's recent `inspect_journal` window.

**Stage flow:**
1. **Emit `ETCH_STARTED`** with `{sub_bid, scenario_name, increment_index}`.
2. Read the current step-implementation map from the project's `src/` (parallel to how Plan 1 reads step defs for the mechanical check).
3. For each unfulfilled step in the scenario's approved `gherkin_body`:
   1. Determine the **inner TDD loop unit** for that step (per parent's domain code at natural granularity: function/method, class, expression, or adapter — per memory resolution).
   2. Call `EtchAgent.run(step, scenario_context, carry_forward)` to produce the next red unit test.
   3. Write the red test to the project's test directory.
   4. Run tests; confirm the new test FAILS (mechanical red).
   5. Emit `ETCH_RED_CONFIRMED` with `{sub_bid, step_name, test_path, increment_id}`.
4. **Emit `ETCH_COMPLETED`** with `{sub_bid, scenario_name, red_test_count}`.

**Why a stage, not just an agent:** Etch's red-test confirmation is a mechanical (run-tests-and-check-fail) gate; it must be a stage so its result is durable in the events log and recoverable across halts.

### `RealizeStage` (orchestration, Plan 4)

A `StageNode` that runs **per scenario** after `ETCH_COMPLETED`. Position: per scenario, sub-or-sibling of Etch. Iterates with Etch in the inner cycle.

**Stage flow:**
1. **Emit `REALIZE_STARTED`** with `{sub_bid, scenario_name, increment_index}`.
2. For each red test from Etch:
   1. Build the Realize prompt (Plan 4's `RealizeAgent.run`): step + scenario context + carry-forward window (injected recent entries from `inspect_journal`) + the red test.
   2. Implement minimal code change to make the test green.
   3. Run all tests; confirm green.
   4. **Refactor** — pull out duplication, rename, simplify. Tests must remain green.
   5. Emit `REALIZE_INCREMENT_DONE` with `{sub_bid, increment_id, files_changed}`.
3. Once all increments are green and refactored for the scenario:
   1. Run the **scenario's outer green check** — the scenario's gherkin body, with step defs resolved, must compile and pass.
   2. Emit `SCENARIO_OUTER_GREEN` with `{sub_bid, scenario_name}`.
4. **Emit `REALIZE_COMPLETED`** with `{sub_bid, scenario_name, increment_count}`.

**Iteration budget:** `per_loop_max_iterations` from `HostConfig` is consumed jointly by Realize and per-loop Inspect within this scenario's cycle. If exhausted, emit `SCENARIO_HALT_PERSISTED` and raise `ScenarioInspectHalted`.

### `InspectLoopStage` (orchestration, Plan 4)

A `StageNode` that runs **per increment** (or per scenario's outer green attempt). Position: after each `REALIZE_INCREMENT_DONE` event in the scenario's inner cycle.

**Stage flow:**
1. **Emit `INSPECT_LOOP_STARTED`** with `{sub_bid, scenario_name, increment_id}`.
2. **Mechanical pre-check on the increment** (R19):
   - `tests_pass` (run all project tests, expect green).
   - `step_definitions_resolvable` (if new step defs).
   - `outer_still_green` (scenario's outer test must still pass).
   - `lifecycle_status_tag_current` (mapping state matches tag).
3. If mechanical fail (any check):
   - Emit `INSPECT_LOOP_FAILED` with `{sub_bid, increment_id, failed_check, findings}`.
   - Emit `INSPECT_JOURNAL_APPENDED` with each finding (route = `code` for mechanical, per R20).
   - Increment `PipelineContext.iteration` (per-scenario counter).
   - If iteration >= `per_loop_max_iterations`: emit `SCENARIO_HALT_PERSISTED` + raise `ScenarioInspectHalted`.
   - Else: return to Realize with the finding as carry-forward.
4. **`IncrementQualityReviewer.run(increment_diff, new_test, scenario_context, recent_journal_window)`** → `ReviewerVerdict`.
5. Persist verdict to mapping artifact journal; emit `INSPECT_JOURNAL_APPENDED` per finding with `route` reflecting the finding's tagged destination (spec / code / cosmetic).
6. **Decision gate (R20 routing-driven):**
   - All findings route=`cosmetic` OR zero findings → emit `INSPECT_LOOP_PASSED`; advance to next increment (or trigger outer-green check if this was the scenario's last increment).
   - Any finding route=`code` → append to journal (next Realize prompt picks it up automatically via carry-forward injection, R21); emit `INSPECT_LOOP_PASSED`; advance. Iteration counter does **not** increment on code-route findings.
   - Any finding route=`spec` → emit `SCENARIO_HALT_PERSISTED` + raise `ScenarioInspectHalted` (spec-route treated as halt-condition even within budget; honors parent v2 design doc's "model cannot make spec changes during Realize" discipline).
   - Any finding route=`cosmetic` alongside other findings → append to `feature_cosmetic_queue`; route gates as above apply.
7. **Emit `INSPECT_LOOP_COMPLETED`** with `{sub_bid, scenario_name, increment_id, route_breakdown: dict[str, int]}`.

### `IncrementQualityReviewer` (Plan 4 — single-dimensional)

A `ReviewerAgent` subclass (Plan 3's `verification/reviewers/base.py` ABC) for `dimension = "increment_quality"`. Distinct from the 7 Inscribe reviewers because:

- Prompts are about **the diff under review**, not the scenario text.
- Findings carry 3-route tagging (R20) instead of severity-only.

**Prompt inputs:**
- Increment diff (files changed this Realize increment).
- New test code.
- Scenario's approved steps.
- Recent journal window (default 5 entries, host-configurable).

**Prompt outputs:** `ReviewerVerdict` with `findings` enriched with a `route` field (R20 routes). The reviewer is constrained to pick a route per finding during generation.

**Why one reviewer, not 7:** Per-loop runs many times; 7 LLM calls per increment breaks the cadence. The end-of-feature Inspect covers the other dimensions at full feature scope.

### `InspectFeatureStage` (orchestration, Plan 5)

A `StageNode` that runs **once per feature** after all scenarios are `live`. Position: after the last scenario emits `SCENARIO_LIVE` (which triggers when `INSPECT_LOOP_PASSED` + outer-green holds for the scenario).

**Stage flow:**
1. **Emit `INSPECT_FEATURE_STARTED`** with `{feature_id, scenario_count, iteration, eof_max_iterations}`.
2. **Mechanical pre-check at feature level** — full Plan 1 mechanical set (all 7 checks).
3. **Per-scenario scenario-level reviews** — for each scenario: `spec_compliance`, `scenario_clarity`, `step_grammar`, `testability`, `determinism`, `naming_idiom`, `lifecycle_tags` (same as Inscribe, scoped to the now-live scenario).
4. **Cross-scenario review** — `CrossScenarioReviewer.run(feature_summary, all_scenarios, mapping)`.
5. **Severity routing (R22):**
   - **Critical:** Identify affected scenarios (from finding citations + dependency inference); transition affected scenarios to `needs_refactor`; emit `SCENARIO_NEEDS_REFACTOR` per affected; transition feature status to `inspect_pending`; persist InspectArtifact.
   - **Important:** Build a fix-wave brief from all Important findings; dispatch a fix-wave subagent; on completion, re-run Inspect-feature.
   - **Minor:** Append all Minor findings to `feature_cosmetic_queue`.
6. Build `InspectArtifactContent`; call `InspectArtifact.finalize(...)`; emit `INSPECT_FEATURE_FINALIZED`.
7. If after routing all-Critical scenarios become `live` again OR all Important-finding fixes applied + Minor appended, set `ready_to_merge: true`; emit `INSPECT_FEATURE_PASSED`; transition feature status to `inspect_passed`.
8. If iteration >= `eof_max_iterations` and `ready_to_merge` still false: emit `INSPECT_FEATURE_HALT_PERSISTED`; raise `InspectFeatureHalted`.
9. **Emit `INSPECT_FEATURE_COMPLETED`** with `{feature_id, iteration, ready_to_merge, scenario_statuses}`.

### `CrossScenarioReviewer` (Plan 5 — end-of-feature-only)

A `ReviewerAgent` subclass for `dimension = "cross_scenario"`. The 8th reviewer dimension, used only in `InspectFeatureStage`. Reviews the whole feature as one unit:

- **Shared state leaks** — multiple scenarios read/write the same domain object in ways that conflict.
- **Ordering dependencies** — scenarios that must run in a particular order that the per-scenario reviews don't observe.
- **Integration gaps** — places where two scenarios' domain models touch but neither scenario's test exercises the boundary.
- **Cross-scenario naming/tag collisions** — naming patterns or tag conventions that drift across scenarios.

**Not registered in Plan 3's `default_reviewer_registry()`.** Added to a separate `feature_reviewer_registry()` for Plan 5's stage-only use.

### `SettleFeatureStage` (orchestration, Plan 5)

A `StageNode` running **once per feature** after `InspectFeatureStage.ready_to_merge == True`.

**Stage flow:**

1. **Emit `SETTLE_FEATURE_STARTED`** with `{feature_id, cosmetic_queue_size}`.
2. Aggregate per-scenario cosmetic queues + Inspect-feature's Minor queue into `MappingArtifact.feature_cosmetic_queue`. Emit `SETTLE_COSMETIC_QUEUED` with `{feature_id, queue_size}`.
3. Write cosmetic queue to a human-readable file at `<project_dir>/.haileris/settle/<feature_id>-cosmetic.md`.
4. **Branch finalization (R25):**
   1. Run `uv run pytest -v` (or host-configured test command). On failure, halt with `SETTLE_TESTS_FAILED` event and exit (resume re-enters Settle).
   2. Detect environment via `git rev-parse --git-dir` vs `git rev-parse --git-common-dir`.
   3. Present the 4 options menu via CLI (interactive) or argument (non-interactive mode for CI).
   4. Execute the chosen option:
      - **Merge:** checkout base, pull, merge, re-verify tests, delete feature branch.
      - **Push + PR:** `git push -u origin <branch>`, optionally `gh pr create` if `--open-pr` flag is set.
      - **Keep:** do nothing.
      - **Discard:** require typed confirmation, force-delete branch + cleanup worktree.
   5. Run worktree cleanup for Options 1 + 4 (provenance check: only `.worktrees/`-style worktrees; harness-owned left in place).
   6. Emit `SETTLE_FEATURE_FINALIZED` with `{feature_id, disposition}`.
5. Write `SettleReport` to `<project_dir>/.haileris/settle/<feature_id>.md`.
6. **Emit `SETTLE_FEATURE_COMPLETED`**.

### `PipelineGraph` halt semantics (Plan 4 + 5)

Extend Plan 3's halt catching (currently handles `PlanRevisionRequired` + `ReviewBudgetExhausted`) to also catch:

- `ScenarioInspectHalted` — feature continues; remaining scenarios proceed; halted scenario's state is on disk via `inspect_journal` and `MappingArtifact.feature_status`.
- `InspectFeatureHalted` — feature halts entirely; `MappingArtifact.feature_status = "halted"`; resume re-enters `InspectFeatureStage`.

CLI surface (added to `mage run --resume`):

- `mage inspect show <feature_id>` — read InspectArtifact + render ledger.
- `mage settle run <feature_id>` — explicitly drive Settle-feature (for cases where the stage was skipped or where `--settle-only` resume is desired).

### Event types (Plan 4 + 5 additions to `EventType` enum)

Approximately 14 new members, matching the existing EventType pattern:

- `ETCH_STARTED`, `ETCH_RED_CONFIRMED`, `ETCH_COMPLETED`
- `REALIZE_STARTED`, `REALIZE_INCREMENT_DONE`, `REALIZE_COMPLETED`, `SCENARIO_OUTER_GREEN`, `SCENARIO_LIVE`
- `INSPECT_LOOP_STARTED`, `INSPECT_LOOP_PASSED`, `INSPECT_LOOP_FAILED`, `INSPECT_LOOP_COMPLETED`, `INSPECT_JOURNAL_APPENDED`
- `SCENARIO_HALT_PERSISTED` (spec-route halt)
- `INSPECT_FEATURE_STARTED`, `INSPECT_FEATURE_PASSED`, `INSPECT_FEATURE_FINALIZED`, `INSPECT_FEATURE_HALT_PERSISTED`, `INSPECT_FEATURE_COMPLETED`
- `SETTLE_FEATURE_STARTED`, `SETTLE_COSMETIC_QUEUED`, `SETTLE_TESTS_FAILED`, `SETTLE_FEATURE_FINALIZED`, `SETTLE_FEATURE_COMPLETED`

### Carry-forward prompt injection

The `RealizeAgent.run()` signature (Plan 4):

```python
class RealizeAgent:
    def run(
        self,
        *,
        step: StepSpec,
        scenario: ScenarioSpec,
        red_test_path: Path,
        carry_forward: list[InspectJournalEntry],  # injected recent window
        cross_scenario_observations: list[InspectJournalEntry],  # last 3 cross-scenario entries
    ) -> RealizeOutput:
        ...
```

The prompt-builder folds the carry-forward into a markdown summary section (severity, location, route, issue, rationale). Default window sizes (5 + 3) are host-configurable.

## Testing Strategy

### Unit tests

- **Mechanical pre-check on increment** (`tests/test_inspect_loop_mechanical.py`): 4 checks × ~3 cases each.
- **`IncrementQualityReviewer`** (`tests/test_reviewers/test_increment_quality.py`): canned `ReviewerVerdict` via `TestModel(custom_output_args=...)` (parallel to Plan 3's 7 reviewer tests). All 3 routes exercised.
- **`CrossScenarioReviewer`** (`tests/test_reviewers/test_cross_scenario.py`): canned `ReviewerVerdict` covering all 4 review foci.
- **`InspectArtifact`** (`tests/test_inspect.py`): finalize/load/digest-mismatch; parallel to `tests/test_verdict.py`.
- **`MappingArtifact` extensions** (`tests/test_mapping.py` additions): `append_inspect_journal`, `attach_feature_inspect`, `append_cosmetic`, `feature_resume_state`.
- **`HostConfig` extensions** (`tests/test_host_overrides.py` additions): defaults, overrides, validation.
- **`InspectJournalEntry` schema** (`tests/test_inspect_models.py`).
- **Per-scenario retry math** (deterministic test, no real LLM): given a sequence of Mechanical+reviewer outcomes, does the increment advance / halt / overflow correctly?

### Integration tests

- **`RealizeStage` carry-forward injection** (`tests/test_realize_stage.py`): stage receives a journal, builds prompt, asserts carry-forward section appears.
- **`InspectLoopStage` end-to-end** (`tests/test_inspect_loop_stage.py`): mechanical pass + reviewer pass → emit `INSPECT_LOOP_PASSED`; mechanical fail → return to Realize; reviewer spec-route → halt.
- **`InspectFeatureStage` orchestration** (`tests/test_inspect_feature_stage.py`): all-pass → `ready_to_merge: true`; Critical → affected scenarios re-enter Realize; Important → fix-wave brief dispatched (mock subagent); budget exhausted → halt.
- **`SettleFeatureStage` cosmetic + finalization** (`tests/test_settle_feature_stage.py`): cosmetic queue aggregation; `SettleReport` written; option dispatch (mock each of the 4).
- **PipelineGraph halt catching** (added to `tests/test_graph.py`): both halt exceptions caught; mapping state preserved; resume re-enters correct stage.

### End-to-end tests

- **E2E happy-path through Inspect + Settle** (`tests/test_e2e_inspect_settle.py`): 1 feature × 2 scenarios × 3 Realize increments each → all live → Inspect-feature passes first try → cosmetic queue populated → Settle offers 4 options. Expected: ledger entry recorded; cosmetic file written; choose "keep as-is" → disposes with `SETTLE_FEATURE_FINALIZED {disposition: "kept"}`.
- **E2E per-scenario halt resume** (`tests/test_e2e_per_loop_halt.py`): scenario hits `per_loop_max_iterations` → resume picks up.
- **E2E Inspect-feature halt + resume** (`tests/test_e2e_inspect_halt.py`): Critical findings → budget exhausted → re-enter → fix → second pass passes.
- **E2E cosmetic queue** (`tests/test_e2e_cosmetic_queue.py`): minor findings accumulate across the cycle + Inspect-feature → Settle surfaces them as a single queue file.
- **State machine test** (deterministic): `MappingArtifact.feature_status` transitions through `pending → live_assembling → inspect_pending → inspect_passed → settled` and `* → halted` paths.

### Visual interaction tests

- **`mage inspect show <feature_id>`**: renders ledger markdown; nested cross_scenario findings show separately.
- **`mage settle run <feature_id>`** (interactive): 4-option menu parses user input correctly; rejects invalid choices; handles `--non-interactive --disposition <name>` for CI.

## Compatibility with Prior Plans

- **Plan 1 (Foundation):** MechanicalVerifier's 7 checks are reused unchanged. Per-loop Inspect uses a subset (4 checks); end-of-feature Inspect uses all 7.
- **Plan 2 (Decomposition + Plan):** Behavior enumeration + PlanArtifact + `mage plan revise` are upstream of all of Plan 4 + 5; their halt/resume semantics are preserved (`PlanRevisionRequired` still halts the whole feature, just like before).
- **Plan 3 (Inscribe + 7 Reviewers + Verdict Format):** The 7 Inscribe reviewer dimensions are reused unchanged in Inspect-feature's full sweep. `ReviewerAgent` ABC + `ReviewerVerdict` / `ReviewerFinding` schemas are extended slightly with a `route` field for `IncrementQualityReviewer` (cosmetic/code/spec) — kept optional so Plan 3's 7 reviewers don't have to know about it. `VerdictArtifact` is unchanged; `InspectArtifact` is a new sibling, not a replacement.

## Plan Decomposition

This design will produce **two plans**:

- **Plan 4: Etch + Realize + Inner TDD Loop**
  - Tasks 1-N: foundation extension (HostConfig, MappingArtifact, EventType, InspectJournalEntry schema).
  - Tasks N+1..M: per-scenario cycle (Etch, Realize, InspectLoop, IncrementQualityReviewer).
  - Tasks M+1..L: integration + carry-forward + halt semantics.
  - Tasks L+1..Z: end-to-end tests.
- **Plan 5: Inspect-feature + Settle-feature**
  - Tasks 1-N: InspectArtifact + CrossScenarioReviewer + end-of-feature extensions.
  - Tasks N+1..M: InspectFeatureStage + 3-tier severity routing + fix-wave orchestration.
  - Tasks M+1..L: SettleFeatureStage + cosmetic queue handoff + finishing-equivalent.
  - Tasks L+1..Z: end-to-end tests.

Both plans use the subagent-driven-development execution harness (fresh subagent per task + per-task review + whole-branch review + fix wave). Both follow the project's conventional-commits style and the project's no-Co-Authored-By trailer rule.

## Deferred / Out of Scope

- **Plan 6 territory:** Parallel reviewer dispatch, Plan-3 deferred findings (Existing9 minor items from Plan 3's whole-branch review), review-meta-aggregator (currently inert in Plan 3 code).
- **Future / follow-up:**
  - Concurrency across scenarios within a feature (Plan 6).
  - Cross-feature lesson carry-forward (a feature-level carry-forward window in addition to per-scenario and cross-scenario windows).
  - Embedded LLM-as-tool usage inside Realize for smarter refactor suggestions (currently Realize is single-shot).
  - Mechanical sub-graph check (formal modeling of step-defs as a graph; Plan 5 only flags misroutes, doesn't prevent).
