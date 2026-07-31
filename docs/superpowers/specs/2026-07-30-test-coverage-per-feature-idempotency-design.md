# Test Coverage + Per-Feature Idempotency — Design (Plan 10)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three remaining Plan 9 review findings: give cosmetic queue entries a `feature_id` discriminator, persist re-apply idempotency state, and ship the six `test_e2e_*` cases the prior spec called for.

**Architecture:** `MappingArtifact.feature_cosmetic_queue` entries grow a required `feature_id` field (validated in the existing model-validator slot). A new `CosmeticAppliedState` artifact, keyed by `sub_bid`, persists already-applied items at `.haileris/cosmetic_applied.yaml` via the existing `FileStatePersistence` pattern. `cmd_cosmetic_show/apply` filter the queue by `args.feature_id` and consult the state for idempotency before writing files or emitting commits. Plan 8's per-instance `asyncio.Lock` covers both `MappingArtifact.save` and the new state file.

**Tech Stack:** Pydantic (artefacts), `FileStatePersistence` (yaml state I/O), pytest-asyncio for the 6 E2E cases. Plan 8 async infrastructure preserved.

**Supersedes:** the deferred-test list in `2026-07-30-stub-completion-design.md` §Testing (Plan 9 spec); the per-feature queue note in the Plan 9 whole-branch review findings.

## Global Constraints

- `haileris_v2` forbidden anywhere in the tree.
- No `Co-Authored-By:` trailers. Conventional Commits only.
- Events are the audit trail; idempotency state changes emit an event.
- Nothing shells out directly from stages; CLI-level `subprocess.run` via `asyncio.to_thread` + `timeout=30` (Plan 9 fix wave).
- Plan 8 concurrency surface preserved: cosmetic refine fan-out uses `asyncio.Semaphore(host_config.max_concurrent_llm_calls)`.
- `MappingArtifact` is digest-pinned; `save` and `load` are still async with per-instance lock (Plan 8).
- New state file `CosmeticAppliedState` mirrors the same lock pattern.
- 410-test baseline must remain green.
- Idempotency state is **per sub_bid** (the unit of applied work), not per `content_hash`. Re-applying the same `sub_bid` with a different `replacement_text` is a fresh apply (different hash → state-record update, not skip).

## Components

### Schema changes

`src/mage/artifacts/mapping.py`:
- `schema_version: int = 2` (was 1; bump mandatory).
- `feature_cosmetic_queue` items gain a required `feature_id: str`. Validation: non-empty string. Existing `append_cosmetic(feature_id, item)` helper updated to take `feature_id`; call sites updated.
- Migration: no backfill. Schema-version mismatch raises on `MappingArtifact.load` (existing pattern).

### State persistence

`src/mage/artifacts/cosmetic_state.py` (new):

```python
class CosmeticApplied(BaseModel):
    content_hash: str
    applied_at: datetime
    file: Path
    rationale: str

class CosmeticAppliedState(BaseModel):
    applied: dict[str, CosmeticApplied] = Field(default_factory=dict)
```

Functions:
- `load_state(project_dir) -> CosmeticAppliedState` — reads `.haileris/cosmetic_applied.yaml`; returns empty state on missing/corrupt.
- `save_state(project_dir, state)` — atomic write via `FileStatePersistence`-style temp+rename; holds per-instance lock.
- `is_already_applied(state, sub_bid, content_hash) -> bool` — pure helper, reads only.

### CLI

`src/mage/cli.py`:
- `cmd_cosmetic_show(args)`: filter `mapping.feature_cosmetic_queue` by `args.feature_id` before refining.
- `cmd_cosmetic_apply(args)`: same filter; after a successful apply, append `CosmeticApplied` to `state.applied[item.sub_bid]` + save state. Skip+emit `COSMETIC_ITEM_SKIPPED` when `is_already_applied(...)` returns True.
- Idempotency contract: `args.dry_run` does NOT update idempotency state (a dry-run apply skips the state write so re-running with `--dry-run` still emits SKIPPED → APPLIED transitions for observability).

### EventTypes

No new members; existing 4 (Plan 9): `COSMETIC_ITEM_APPLIED`, `COSMETIC_ITEM_SKIPPED`, `COSMETIC_APPLY_FAILED`, `COSMETIC_REFINER_FALLBACK`.

## Data Flow

### `mage cosmetic show <feature_id>`

```
1. Parse args (project_dir, feature_id)
2. Load MappingArtifact(project_dir/mapping.yaml)
3. queue = [q for q in mapping.feature_cosmetic_queue
            if q.get("feature_id") == feature_id]
4. If empty: print "no items for <feature_id>", return 0
5. Refine queue → print table
```

### `mage cosmetic apply <feature_id> [--dry-run]`

```
1. Parse args
2. Load MappingArtifact
3. Filter queue by feature_id (as above)
4. Load CosmeticAppliedState (empty if missing)
5. Refine queue via asyncio.gather + Semaphore(host_config.max_concurrent_llm_calls)
6. For each item:
    if item.file_path is None → emit COSMETIC_REFINER_FALLBACK, continue
    if is_already_applied(state, item.sub_bid, item.content_hash)
        → emit COSMETIC_ITEM_SKIPPED, continue
    target = project_dir / item.file_path
    if not target.exists() → emit COSMETIC_APPLY_FAILED("file-missing"), continue
    try:
        backup lines + write new
        if not args.dry_run:
            await asyncio.to_thread(subprocess.run, ["git","commit","-am",...],
                                    cwd=project_dir, check=True, timeout=30)
        if not args.dry_run:
            state.applied[item.sub_bid] = CosmeticApplied(
                content_hash=item.content_hash, applied_at=now,
                file=item.file_path, rationale=item.rationale)
            save_state(project_dir, state)
        emit COSMETIC_ITEM_APPLIED
    except Exception as e → emit COSMETIC_APPLY_FAILED(reason=str(e),
                                                      error_type=type(e).__name__)
```

### Error matrix

| Failure | Event | Continues? |
|---|---|---|
| LLM fails (refiner) | `COSMETIC_REFINER_FALLBACK` | yes |
| Idempotency hit | `COSMETIC_ITEM_SKIPPED` | yes |
| File missing | `COSMETIC_APPLY_FAILED("file-missing")` | yes |
| Line-range out of bounds | `COSMETIC_APPLY_FAILED` with `error_type` | yes |
| git commit fail | `COSMETIC_APPLY_FAILED` | yes (file edited, no commit) |
| Save-state fail | `COSMETIC_APPLY_FAILED(reason="state-save-failed")` | yes (file+commit done, audit-only) |
| `asyncio.to_thread` timeout | `COSMETIC_APPLY_FAILED(reason="git-timeout")` | yes |

### Locking

- `MappingArtifact.save` lock: independent.
- `CosmeticAppliedState.save_state` lock: independent, held only for the duration of `save_state`.
- No two locks ever held at once (no deadlock surface).

## Testing

### Unit

`tests/unit/test_cosmetic_state.py` (new):
- `test_cosmetic_state_load_returns_empty_when_missing`
- `test_cosmetic_state_save_then_load_round_trip`
- `test_cosmetic_applied_serializes_via_pydantic`
- `test_is_already_applied_returns_false_when_sub_bid_missing`
- `test_is_already_applied_returns_true_when_hash_matches`
- `test_is_already_applied_returns_false_when_hash_differs`

`tests/unit/test_mapping_feature_id.py` (new):
- `test_feature_cosmetic_queue_entry_requires_feature_id`
- `test_append_cosmetic_takes_feature_id_and_appends`
- `test_feature_cosmetic_queue_round_trips_via_save_load`

`tests/unit/test_cli.py` (additive):
- `test_cosmetic_show_filters_by_feature_id`
- `test_cosmetic_apply_filters_by_feature_id`
- `test_cosmetic_apply_skips_already_applied_with_matching_hash`
- `test_cosmetic_apply_reapplies_when_hash_differs`

### Feature (6 tests spec-mandated, all land now)

`tests/features/test_e2e_etch_llm.py`:
- `test_e2e_etch_stage_with_real_llm_wiring`
- `test_e2e_inspect_loop_runs_after_etch`

`tests/features/test_e2e_cosmetic_apply.py`:
- `test_e2e_cosmetic_apply_writes_files_and_commits`
- `test_e2e_cosmetic_apply_idempotent`
- `test_e2e_cosmetic_apply_failed_event_on_missing_file`

`tests/features/test_e2e_mage_run_no_dry_run.py`:
- `test_e2e_mage_run_without_dry_run` (gated by `HOST_MODEL_API_KEY` env var; CI skip)

## Task layout

1. `CosmeticApplied` + `CosmeticAppliedState` schema (foundation)
2. `MappingArtifact` `schema_version=2` + `feature_id` validator + helper update
3. `cosmetic state persistence` (load/save helpers)
4. `cmd_cosmetic_show` filter by `feature_id`
5. `cmd_cosmetic_apply` filter + idempotency state-write
6. E2E cosmetic apply (success + idempotent + missing-file)
7. E2E EtchStage + InspectLoop + `mage run`

## Edge cases

- Empty mapping queue (no items match `feature_id`): no events, exit 0.
- State file corrupt on load: log warning, return empty state (fail-open, not fail-closed).
- Two parallel `mage cosmetic apply` invocations: state lock serializes; second one sees the first's updates.
- `content_hash` collision across different `sub_bid`s: state keyed by sub_bid, so independent.
- `--dry-run` re-run: emits `COSMETIC_ITEM_APPLIED` again (state NOT updated); user re-running for real sees idempotency apply correctly.

## Handoff (post-Plan 10)

- Cosmetic application daemon — long-running watcher that reacts to `MappingArtifact.save` events and re-applies new items.
- Review-meta-aggregator — cross-feature retrospective summary (Plan 5 deferred).
- Pydantic-Graph full async node-traversal — only relevant if branching scenarios are introduced.
- `mage cosmetic watch` — natural follow-up now that idempotency exists.

## Spec Self-Review

1. Placeholder scan: no TBD/TODO. All event names, field names, file paths, error codes pinned.
2. Internal consistency: schema_version bump matches the digest-pinned load pattern from Plan 1; CosmeticItem's existing `content_hash` is reused (no schema change there).
3. Scope check: 7 tasks, 3 subsystems tightly coupled (queue schema + idempotency + E2E). Single plan justified.
4. Ambiguity check: per-feature filtering pinned to dictionary lookup, not optional; idempotency keyed by sub_bid (not content_hash); dry-run pinned to skip state-write so re-runs are observable.
