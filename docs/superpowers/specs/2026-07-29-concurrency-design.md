# Concurrency — Design (Plan 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add asyncio-based parallelism to LLM-bound and read-only operations while preserving sequential-per-scenario discipline (Plan 7 P2) and serialized writes to shared artifacts.

**Architecture:** `graph.run()` becomes an async coroutine. StageNodes gain async `_run` methods. `asyncio.gather` fires independent calls; `asyncio.Lock` per write target serializes only the contended regions. `PipelineContext.current_sub_bid` becomes thread-safe (asyncio Lock inside the discipline module). `HostConfig.max_concurrent_llm_calls` knob (default 7) caps gather fan-out via `asyncio.Semaphore`.

**Tech Stack:** `asyncio` (stdlib), `pytest-asyncio` (test runner), existing Pydantic-Graph + Pydantic-AI (already async-capable).

**Supersedes scope of:** the "Plan 8" placeholder in `2026-07-28-pipeline-wiring-design.md` (line 27).

## Global Constraints

- The string `haileris_v2` is forbidden anywhere in the tree (AGENTS.md).
- Commits follow Conventional Commits. No `Co-Authored-By` trailers (CLAUDE.md).
- Events are the audit trail. Any new stage outcome gets an `EventType` member and an emitted `Event` (AGENTS.md).
- Nothing shells out directly. Stages take an injected `command_runner`; tests substitute a recording fake (AGENTS.md).
- Plan 7 P2 (sequential per-scenario cycles) is preserved verbatim. Plan 8 does NOT introduce parallel-scenario processing.
- Sequential artifacts (`MappingArtifact`, `EventsLog`) get per-instance `asyncio.Lock`. Writes serialize; reads (append-only JSONL) stay lock-free.
- `HostConfig` is frozen + `extra="allow"`. New fields follow the existing pattern.
- All existing tests must remain green (381 baseline).

## Concurrency Surface

### Parallel today

| Operation | Concurrency mechanism | Cap |
|---|---|---|
| 7 reviewers per scenario (Inscribe) | `asyncio.gather` over reviewers | `max_concurrent_llm_calls` semaphore |
| InspectFeature across scenarios | `asyncio.gather` over scenario Inspect runs | same |
| Cosmetic queue items (Settle) | **Deferred to Plan 9** — no per-item LLM processing exists today; cosmetic items are rendered as a single markdown report. When Plan 9 introduces per-item application/refinement, it will use the same semaphore cap. | (deferred) |

### Sequential (Plan 7 P2)

- Per-scenario cycle: Inscribe → Etch → Realize → Inspect-loop → Live for a given `sub_bid` runs serially.
- Mapping.yaml writes: one writer at a time across the pipeline (per-instance lock on `MappingArtifact`).
- events.jsonl appends: one writer at a time across the pipeline (per-instance lock on `EventsLog`).

## Architecture

### Component changes

| File | Change |
|---|---|
| `src/mage/orchestration/graph.py` | `run()` becomes `async def run()`; uses `await` for stage execution. CLI wraps with `asyncio.run()`. |
| `src/mage/orchestration/nodes.py` | `StageNode._run` becomes `async`; `run()` wraps with `await self._run(...)`. |
| `src/mage/orchestration/events.py` | `EventsLog.append` acquires internal `asyncio.Lock`; `read_all` and `read_since` stay lock-free (append-only JSONL). |
| `src/mage/artifacts/mapping.py` | `MappingArtifact.save` acquires internal `asyncio.Lock` on the instance; `load` stays lock-free. |
| `src/mage/orchestration/discipline/policy.py` | `acquire_cycle_lock`/`release_cycle_lock` become async; use `PipelineContext._cycle_lock` (asyncio.Lock per context). |
| `src/mage/verification/host_overrides.py` | Add `max_concurrent_llm_calls: int = 7` to `HostConfig`. |
| `src/mage/orchestration/inscribe.py` | `InscribeStage._run` becomes async; reviewers dispatched via `asyncio.gather` with `asyncio.Semaphore(host_config.max_concurrent_llm_calls)`. |
| `src/mage/orchestration/inspect_feature.py` | `InspectFeatureStage._run` becomes async; per-scenario Inspect dispatched via `asyncio.gather` with semaphore. |
| `src/mage/orchestration/settle_feature.py` | `SettleFeatureStage._run` becomes async. Cosmetic queue item dispatch via `asyncio.gather` + semaphore is deferred to Plan 9, when per-item LLM processing is introduced. |

### Write coordination

`asyncio.Lock` per `EventsLog` instance and per `MappingArtifact` instance. StageNodes acquire the lock only for read-modify-write cycles. Pure reads (`read_all`, `load`) don't lock — the append-only JSONL format guarantees consistency for readers, and atomic write-then-rename on mapping.yaml (Plan 1) means readers see either the old or new full file.

### DisciplineStage + cycle lock thread safety

`PipelineContext` gains `_cycle_lock: asyncio.Lock | None = None` (lazily created). `acquire_cycle_lock(context, sub_bid)` becomes `async def`, awaits the lock, then performs the existing check. `release_cycle_lock` similarly becomes async. P2 sequential rule still holds: only one scenario's cycle holds the lock at any time; `await lock` is the only path to acquisition.

### HostConfig knob

```python
class HostConfig(BaseModel):
    # ... existing fields ...
    max_concurrent_llm_calls: int = 7  # Plan 8: asyncio.Semaphore cap for LLM fan-out
```

`InscribeStage`, `InspectFeatureStage`, `SettleFeatureStage` read this and construct `asyncio.Semaphore(host_config.max_concurrent_llm_calls)`. Operators can throttle rate-limited hosts by lowering this (e.g., `max_concurrent_llm_calls: 2` for free-tier API keys).

## Testing

### Unit (tests/unit/test_events_log_lock.py — new)

- `test_concurrent_appends_serialize`: 10 concurrent `await log.append(...)` calls produce exactly 10 lines in order.
- `test_reads_unaffected_by_writes`: `read_all()` during a concurrent write set still returns valid JSONL.

### Unit (tests/unit/test_mapping_lock.py — new)

- `test_concurrent_saves_serialize`: 5 concurrent `await mapping.save(...)` calls produce a valid file.
- `test_load_during_save_returns_old_or_new`: `MappingArtifact.load` during a concurrent save returns the old OR new file, never partial.

### Unit (tests/unit/test_cycle_lock_async.py — new)

- `test_acquire_blocks_until_release`: two coroutines contending for the cycle lock; second one waits.
- `test_reacquire_same_sub_bid_allowed`: per Plan 7 semantics.
- `test_different_sub_bid_raises_cycle_already_in_progress`: per Plan 7 P2.

### Unit (tests/unit/test_inscribe_stage_async.py — new)

- `test_seven_reviewers_fire_concurrently`: timing assertion (max wall time < 4× single-reviewer time).
- `test_semaphore_caps_concurrency`: with `max_concurrent_llm_calls=2`, at most 2 reviewers are active simultaneously.
- `test_partial_results_on_cancelled_gather`: cancelled gather preserves completed reviewer results in verdicts.

### Unit (tests/unit/test_graph_async.py — new)

- `test_graph_run_is_coroutine`: returns awaitable.
- `test_graph_runs_stages_in_order`: existing test, adapted for async.
- `test_graph_dispatches_discipline_events_async`: tail-dispatch pattern works under async.

### Feature (tests/features/test_e2e_concurrency.py — new)

- `test_e2e_inscribe_with_seven_reviewers_concurrently`: full Inscribe pipeline runs end-to-end with parallel reviewers.
- `test_e2e_inspect_feature_across_scenarios_concurrently`: multiple scenarios' Inspect runs in parallel.

### Backward compatibility

- `mage run` CLI: `def cmd_run(args)` calls `asyncio.run(graph.run(context))`.
- Existing sync tests (`test_graph.py` etc.) keep their sync assertions; they call `asyncio.run()` internally via a thin wrapper or are updated to `async def` + `pytest.mark.asyncio`.
- Dry-run path works unchanged (stubs don't await LLM calls).

## Edge cases

- **Cancelled reviewer**: `asyncio.CancelledError` propagates; partial results in completed verdicts are kept; scenario reverts to inscribing (Plan 7 P5).
- **Rate-limit 429**: gather returns partial results; caller treats as `REVIEW_HALT_PERSISTED` and emits the appropriate event.
- **Lock acquisition during shutdown**: `asyncio.Lock` cleanup happens on event-loop close; no special handling needed.
- **Concurrent same-target writes**: `EventsLog` lock serializes; `MappingArtifact.save` lock serializes. Reads see consistent snapshots via atomic rename.

## Handoff

- **Plan 9 (stub completion):** ships the LLM agents that benefit most from Plan 8's concurrency (especially `EtchAgent` and the 7 reviewers with real model wiring). Plan 9 will also introduce the cosmetic-queue per-item LLM processing that Plan 8 spec'd but deferred — when that processing exists, the same `max_concurrent_llm_calls` semaphore cap will apply.
- **Future plan (post-Plan 9):** Pydantic-Graph's full async node-traversal machinery if branching scenarios are ever introduced. Plan 8 deliberately keeps `graph.py` as a linear async orchestrator.

## Spec Self-Review

1. **Placeholder scan:** No "TBD"/"TODO"/incomplete sections. Concurrency surface enumerated, edge cases listed, handoff to Plan 9 pinned.
2. **Internal consistency:** Plan 7 P2 verbatim preserved. Lock infrastructure matches existing `FileStatePersistence` write-temp-then-rename pattern (Plan 1). HostConfig addition matches the existing `extra="allow"` pattern.
3. **Scope check:** Single plan focus — concurrency infrastructure. Touches `nodes.py`, `graph.py`, `events.py`, `mapping.py`, `discipline/policy.py`, `host_overrides.py`, three stage files, plus tests. Mirrors Plan 6 wiring scope.
4. **Ambiguity check:** "Parallel today" pinned to three specific operations (reviewers, InspectFeature across scenarios, cosmetic queue). "Sequential" pinned to per-scenario cycle + shared artifact writes. Semaphore cap pinned to `HostConfig.max_concurrent_llm_calls`. Backward compat pinned (CLI uses `asyncio.run`, sync tests adapt via wrapper).
