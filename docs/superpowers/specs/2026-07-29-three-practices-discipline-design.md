# Three Practices Discipline Enforcement — Design (Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the Three Practices (Discovery → Formulation → Automation) and their recurrence rules (revision, supersession) as a first-class pipeline concern, with full audit trail in the mapping artifact.

**Architecture:** One `DisciplineStage` (Pydantic-Graph node) subscribed to stage events. A pure `src/mage/orchestration/discipline/policy.py` module holds the six Approved Gate Scope rules from parent v2 design plus revision and supersession flows. Stage calls policy methods; policy writes audit entries to `BaseBIDEntry.reversion_log` and `BaseBIDEntry.post_live_revisions` (both already exist on `BaseBIDEntry` from Plan 1). Single responsibility: gate enforcement + recurrence handling.

**Tech Stack:** Pydantic-Graph (existing), Pydantic models (existing), `MappingArtifact` with `BaseBIDEntry` per-behavior containers that already carry `reversion_log: list[ReversionLogEntry]` and `post_live_revisions: list[PostLiveRevisionEntry]` fields (Plan 1), `ScenarioEntry.supersedes` / `ScenarioEntry.superseded_by` fields (Plan 1, used for supersession linking), existing `EventType` enum (Plan 1) extended with five new members, existing `PipelineContext` (Plan 6) extended with `current_sub_bid` field for cycle lock.

**Supersedes scope of:** the "Plan 7" placeholder referenced in `2026-07-28-pipeline-wiring-design.md` (line 26).

## Global Constraints

- The string `haileris_v2` is forbidden anywhere in the tree (AGENTS.md).
- Commits follow Conventional Commits. No `Co-Authored-By` trailers (CLAUDE.md).
- Events are the audit trail. Any new stage outcome gets an `EventType` member and an emitted `Event`. Silent branches are defects (AGENTS.md).
- Nothing shells out directly. Stages take an injected `command_runner`; tests substitute a recording fake (AGENTS.md).
- `MappingArtifact.reversion_log` and `MappingArtifact.post_live_revisions` fields already exist from Plan 1. Plan 7 wires the writers — no schema changes.
- Six Approved Gate Scope rules from parent v2 design (`/home/divinefilth/code/github/MistressFilth/haileris-next/docs/superpowers/specs/2026-07-10-haileris-v2-design.md` lines 291-305) are pinned and authoritative.
- Recurrence types from parent v2 design (lines 267-269) are pinned: revision (Formulation → Discovery → Formulation), supersession (any → Discovery → Formulation → Automation for the new scenario). Full supersession only in v1 — partial coverage escalates as Plan revision, not handled here.

## Architecture

### Components

| Component | File | Responsibility |
|---|---|---|
| `Policy` | `src/mage/orchestration/discipline/policy.py` | Pure functions implementing the six rules + revision + supersession + cosmetic guard. No graph dependencies. No side effects beyond raising exceptions and returning updated Pydantic models. Operates on `MappingArtifact` / `BaseBIDEntry` / `ScenarioEntry` instances. |
| `DisciplineStage` | `src/mage/orchestration/discipline/stage.py` | Pydantic-Graph node. Subscribes to stage events. Translates events into policy calls. Emits discipline events. |
| Exceptions | `src/mage/orchestration/discipline/exceptions.py` | `DisciplineViolation` base + `ForwardOrderViolation`, `CycleAlreadyInProgress`, `NotApprovedForAutomation`, `DecompositionOpen`, `ModelCannotApplyCosmetic`. |
| EventType members | `src/mage/orchestration/events.py` | Five new: `SCENARIO_REVERTED_TO_INSCRIBING`, `SCENARIO_REVISION_REQUESTED`, `SCENARIO_SUPERSESSION_REQUESTED`, `SCENARIO_DEPRECATED`, `COSMETIC_QUEUED`. |
| PipelineContext field | `src/mage/orchestration/nodes.py` | `current_sub_bid: str | None` for cycle lock. |

### Trigger model

`DisciplineStage` wakes on stage events emitted by `InscribeStage`, `InspectLoopStage`, `SettleStage`, and the pipeline graph:

| Event | DisciplineStage action |
|---|---|
| `SCENARIO_APPROVED` | Release cycle lock (`context.current_sub_bid = None`). |
| `SCENARIO_LIVE` | If supersession pending on this sub_bid → complete it (old → deprecated). |
| `SCENARIO_HALT_PERSISTED` (spec-route) | Call `Policy.begin_revision(...)`. |
| `SCENARIO_REVISION_REQUESTED` | Call `Policy.begin_revision(...)`. |
| `SCENARIO_SUPERSESSION_REQUESTED` | Call `Policy.begin_supersession(...)`. |
| `COSMETIC_QUEUED` | No-op (audit already written by Settle). |
| Pipeline start | Call `Policy.assert_decomposition_closed(events_log)` and `Policy.assert_independent_gates(mapping)`. |

## The Six Approved Gate Scope Rules (P1-P6)

From parent v2 design lines 291-305. Implementation pinned here.

### P1 — Per-scenario independence

`Policy.assert_independent_gates(mapping: MappingArtifact, sub_bid: str) -> None`

Each scenario's `lifecycle_status` is independent except as constrained by Plan sequencing: scenario N can start only after scenarios 1..N-1 are at least `live`. The Plan's build order is captured in `MappingArtifact.base_bids[*].scenarios` list ordering (positional within each `BaseBIDEntry`). Implementation: collect all scenarios in declared order across all `base_bids`; locate `sub_bid`; for each earlier scenario raise `ForwardOrderViolation` if `lifecycle_status not in {LIVE, DEPRECATED, RETIRED}`.

### P2 — Sequential per-scenario cycles

`Policy.acquire_cycle_lock(context: PipelineContext, sub_bid: str) -> None`

Only one scenario's cycle runs at a time. Implementation: `context.current_sub_bid` field; raise `CycleAlreadyInProgress` if set to a different `sub_bid`. Lock acquired when Inscribe starts (sub-phase entry); released on `SCENARIO_APPROVED` (gate passed) or halt (lock cleared on graph resume).

### P3 — Approved before any Etch/Realize sub-phase

`Policy.guard_automation_entry(scenario: ScenarioEntry) -> None`

No Automation sub-phases start until Formulation reached `approved` for that scenario. Implementation: raise `NotApprovedForAutomation` if `scenario.lifecycle_status != APPROVED`. Called by `AutomationStage` (Plan 6) immediately before dispatching Etch sub-phase.

### P4 — Decomposition closed before any per-scenario cycle starts

`Policy.assert_decomposition_closed(events_log: EventsLog) -> None`

Decomposition closure is signaled by the most recent `PLAN_FINALIZED` or `PLAN_REVISED` event for the project's plan path. Implementation: call `PlanArtifact.load(plan_path, events_log)` semantics — if `PlanNotFinalizedError` raised, raise `DecompositionOpen`; on success, pass. Called once at pipeline start before any scenario's cycle begins.

### P5 — Revision re-applies the gate

`Policy.begin_revision(mapping: MappingArtifact, sub_bid: str, reason: str, originating_stage: str, timestamp: datetime) -> MappingArtifact`

Mid-implementation revert to `inscribing`. Implementation:
1. Locate the `BaseBIDEntry` containing `sub_bid` (raise `BaseBIDNotFoundError` if absent).
2. Replace the scenario in that entry with a copy whose `lifecycle_status == INSCRIBING` via `model_copy(update=...)` (frozen).
3. Append `ReversionLogEntry{sub_bid, timestamp, reason, originating_stage}` to that entry's `reversion_log`.
4. Return updated `MappingArtifact` via `model_copy(update={"base_bids": new_entries})`. Caller persists.

No lighter re-check path. Full mechanical + 7 reviewers re-run on next Inscribe.

### P6 — Reversion log captures why

Wired as part of P5. `ReversionLogEntry` schema (Plan 1) is the source of truth.

## Revision Flow

When implementation surfaces spec ambiguity:

1. **Detection.** Inspect-loop emits `IncrementQualityReviewer` finding with `route="spec"`, or Realize emits an explicit `SCENARIO_REVISION_REQUESTED` event with `{sub_bid, reason, originating_stage}`. Both routes converge on `DisciplineStage`.
2. **Revert.** `DisciplineStage` calls `Policy.begin_revision(mapping, sub_bid, reason, originating_stage, now)`. Writes `ReversionLogEntry`. Emits `SCENARIO_REVERTED_TO_INSCRIBING`.
3. **Re-inscribe.** Pipeline resumes at `InscribeStage` for this scenario. Full mechanical + 7 reviewers re-run.
4. **Re-approve.** New `SCENARIO_APPROVED` event releases cycle lock. `Policy.guard_automation_entry(scenario)` re-applied before Etch resumes.
5. **Audit visibility.** `mapping.reversion_log` accumulates per-BID entries. Pattern detection (recurring reversions on the same scenario, same originating stage) is out of scope for v1.

## Supersession Flow (Full Only in v1)

When a `live` scenario is superseded by a new scenario covering the same behavior:

1. **Detection.** Settle or external trigger emits `SCENARIO_SUPERSESSION_REQUESTED` with `{old_sub_bid, new_sub_bid, reason}`.
2. **Begin supersession.** `Policy.begin_supersession(mapping, old_sub_bid, new_sub_bid, reason, timestamp) -> MappingArtifact`:
   - Locate old and new `BaseBIDEntry` containers.
   - Set old scenario's `supersedes` link: old stays `live`, no status change yet. (Field already exists on `ScenarioEntry`.)
   - Set new scenario's `superseded_by` link → null; new scenario's `supersedes` field set to `old_sub_bid`. (Field already exists on `ScenarioEntry`.)
   - Append `ReversionLogEntry{ sub_bid=old_sub_bid, timestamp, reason, originating_stage="supersession" }` to old entry's `reversion_log`.
   - Old stays `live`. New scenario enters Decomposition with full Discovery → Formulation → Automation cycle.
3. **Complete supersession.** When new scenario emits `SCENARIO_LIVE`, `Policy.complete_supersession(mapping, new_sub_bid, timestamp) -> MappingArtifact`:
   - Locate new scenario; read `new.supersedes` to find old `sub_bid`.
   - Mutate old scenario `lifecycle_status` → `DEPRECATED` via `model_copy`.
   - Set old scenario's `superseded_by` field to `new_sub_bid`.
   - Append `ReversionLogEntry{ sub_bid=old_sub_bid, timestamp, reason="superseded by {new_sub_bid}", originating_stage="supersession_complete" }` to old entry's `reversion_log`.
   - Emit `SCENARIO_DEPRECATED` event.
4. **Partial coverage.** New covers part of old's behavior → escalate as Plan revision per parent v2 design line 339. Not handled in v1.

## Cosmetic Gate

Cosmetic findings (typo, punctuation, grammar, terminology) from Inspect or Settle route to `MappingArtifact.cosmetic_queue` via `append_cosmetic(CosmeticItem)` (Plan 6 stub). Plan 7 ships the gate; the human `mage cosmetic apply` CLI is Plan 9.

`Policy.guard_cosmetic_application(source: str, item: CosmeticItem, human_approver: str | None) -> PostLiveRevisionEntry`:
- `source == "model"` → raise `ModelCannotApplyCosmetic`. No carve-outs. Per parent v2 design line 327: "even narrow model-side carve-outs for trivial fixes create pressure to widen them over time."
- `source == "human"` or `source == "human-authorized"` → build `PostLiveRevisionEntry{sub_bid, timestamp, human_approver, before_hash, after_hash}` and return it. v1 stub: `human_approver` must be non-None string; the apply path itself is not in v1.

The gate is the only enforcement in v1. Plan 9 wires the CLI command that calls `guard_cosmetic_application` with `source="human"`.

## Testing

### Unit (tests/unit/test_discipline_policy.py)

- `test_p1_independent_gates_passes_when_earlier_live`
- `test_p1_independent_gates_passes_when_earlier_deprecated`
- `test_p1_independent_gates_raises_when_earlier_inscribing`
- `test_p1_independent_gates_raises_when_earlier_approved` (build-order: approved not enough, must be live)
- `test_p1_independent_gates_respects_base_bid_ordering`
- `test_p2_acquire_cycle_lock_succeeds_when_unset`
- `test_p2_acquire_cycle_lock_raises_when_held_by_other`
- `test_p2_acquire_cycle_lock_allows_same_sub_bid_reacquire`
- `test_p3_guard_automation_entry_passes_when_approved`
- `test_p3_guard_automation_entry_raises_when_inscribing`
- `test_p3_guard_automation_entry_raises_when_live` (you can't re-enter Automation on a live scenario)
- `test_p4_assert_decomposition_closed_passes_when_plan_finalized_event_present`
- `test_p4_assert_decomposition_closed_passes_when_plan_revised_event_present`
- `test_p4_assert_decomposition_closed_raises_when_no_finalized_event`
- `test_p5_begin_revision_flips_status_to_inscribing`
- `test_p5_begin_revision_appends_reversion_log_entry_to_correct_base_bid_entry`
- `test_p5_begin_revision_preserves_earlier_reversions`
- `test_p5_begin_revision_raises_when_sub_bid_not_found`
- `test_supersession_begin_sets_supersedes_link_on_new`
- `test_supersession_complete_flips_old_to_deprecated`
- `test_supersession_complete_writes_reversion_log_entry`
- `test_cosmetic_guard_rejects_model_source`
- `test_cosmetic_guard_accepts_human_source`
- `test_cosmetic_guard_accepts_human_authorized_source`
- `test_cosmetic_guard_returns_post_live_revision_entry`
- `test_cosmetic_guard_requires_human_approver_for_human_source`

### Unit (tests/unit/test_discipline_stage.py)

- `test_stage_subscribes_to_scenario_approved_releases_lock`
- `test_stage_subscribes_to_scenario_revision_calls_begin_revision`
- `test_stage_subscribes_to_scenario_supersession_calls_begin_supersession`
- `test_stage_subscribes_to_scenario_live_completes_pending_supersession`
- `test_stage_idempotent_on_duplicate_events` (re-emit `SCENARIO_APPROVED` → no error, no duplicate reversion)
- `test_stage_emits_scenario_reverted_to_inscribing_on_revision`
- `test_stage_emits_scenario_deprecated_on_supersession_complete`

### Feature (tests/features/test_e2e_three_practices.py)

- `test_e2e_revision_full_loop`: scenario inscribes → approved → Etch raises spec-route finding → DisciplineStage reverts → re-inscribe → re-approved → Etch succeeds
- `test_e2e_supersession_full_loop`: scenario live → supersession requested → new scenario inscribes → approves → etches → realizes → goes live → old auto-deprecated
- `test_e2e_cosmetic_model_blocked`: scenario live → cosmetic finding routed to queue → model attempts apply → ModelCannotApplyCosmetic raised
- `test_e2e_plan_order_violation`: two scenarios in mapping; scenario 1 inscribing; scenario 2 attempts to start → ForwardOrderViolation
- `test_e2e_decomposition_open_blocks_pipeline_start`: Decomposition open → pipeline start → DecompositionOpen raised

### Regression

- All Plan 6 tests stay green (334 tests). No event types removed; no `MappingArtifact` schema changes.
- Cursor + halt paths from Plan 6 unchanged.

## Handoff

- **Plan 8 (concurrency):** parallel reviewer dispatch, parallel scenario processing. DisciplineStage policy is single-threaded; Plan 8 adds thread/process safety around `context.current_sub_bid` mutation and `MappingArtifact.reversion_log` appends.
- **Plan 9 (stub completion):** ships `mage cosmetic list/apply` CLI that calls `Policy.guard_cosmetic_application(source="human")`. Wires EtchAgent LLM. Completes the deferred-tool pause.

## Spec Self-Review

1. **Placeholder scan:** No "TBD"/"TODO"/incomplete sections. All five new event types named, all five new exceptions named, all six rules mapped to policy methods. "Out of scope for v1" applied to: pattern detection on reversion_log, partial supersession, cosmetic CLI — each justified.
2. **Internal consistency:** Section cross-references verified. P1-P6 match parent v2 design. Revision flow matches parent v2 design Open Question 3 resolution. Supersession matches parent v2 design Pivot #3 + line 269.
3. **Scope check:** Single plan focus — discipline enforcement layer. Touches: `nodes.py` (one field), `events.py` (five enum members), `exceptions.py` (one base + five subclasses), new `discipline/policy.py` + `discipline/stage.py`, plus tests. Wiring changes to existing stages (Inscribe emits `SCENARIO_REVISION_REQUESTED`, Settle emits `SCENARIO_SUPERSESSION_REQUESTED`, AutomationStage calls `guard_automation_entry`) are scoped as small interface additions.
4. **Ambiguity check:** "Full supersession only in v1" pinned. "Audit entry written" pinned to specific fields (per-`BaseBIDEntry`, not project-wide). Supersession uses existing `ScenarioEntry.supersedes` / `superseded_by` fields rather than a new `pending_supersession` field. Cosmetic `human_approver` required non-None for human source. `lifecycle_status` values referenced are exactly the enum members of `LifecycleStatus`: `INSCRIBING`, `APPROVED`, `LIVE`, `DEPRECATED`, `RETIRED`.
