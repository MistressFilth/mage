# Stub Completion — Design (Plan 9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the remaining `NotImplementedError` stubs (EtchAgent, `mage run` without `--dry-run`, InspectFeatureStage linear-graph wiring), introduce per-item cosmetic processing, and ship `mage cosmetic apply` CLI.

**Architecture:** EtchAgent becomes a real Pydantic-AI agent mirroring RealizeAgent. `mage run` no longer requires `--dry-run`. A new CosmeticRefiner agent converts the existing `feature_cosmetic_queue` dicts into concrete `CosmeticItem` records (file_path + line_range + replacement_text). `mage cosmetic apply` reads refined items, atomically writes file edits, and commits per item on the feature branch. `asyncio.Semaphore(host_config.max_concurrent_llm_calls)` caps refiner fan-out.

**Tech Stack:** Pydantic-AI (already wired for InscribeAgent, RealizeAgent, DecompositionAgent), Plan 8 async infrastructure (`asyncio.Semaphore`, per-instance locks on EventsLog/MappingArtifact), pytest-asyncio (test runner).

**Supersedes:** the "Plan 9" placeholder in `2026-07-28-pipeline-wiring-design.md` (Plan 6 spec) and the cosmetic-queue deferral note in `2026-07-29-concurrency-design.md` (Plan 8 spec).

## Global Constraints

- The string `haileris_v2` is forbidden anywhere in the tree (AGENTS.md).
- Commits follow Conventional Commits. No `Co-Authored-By` trailers (CLAUDE.md).
- Events are the audit trail. Any new stage outcome gets an `EventType` member and an emitted `Event` (AGENTS.md).
- Nothing shells out directly. Stages take an injected `command_runner`; tests substitute a recording fake (AGENTS.md).
- `EtchAgent` mirrors `RealizeAgent` plumbing exactly (constructor takes `Model | None`, prompt templated, structured output via `Agent[EtchDeps, RedTestSpec]`).
- All existing tests must remain green (391 baseline).
- Plan 8 concurrency surface preserved: cosmetic refinement uses `asyncio.Semaphore(max_concurrent_llm_calls)`.
- `mapping.feature_cosmetic_queue` keeps its current dict shape (refinement is a runtime step, not a serialization change).

## Components

### EtchAgent LLM wiring

`src/mage/agents/etch.py`:
- Existing `EtchAgent.run` (raises `NotImplementedError`) becomes the abstract base contract.
- New `PydanticEtchAgent(EtchAgent)` is the concrete Pydantic-AI implementation.
- Constructor: `def __init__(self, *, model: Model | None = None)`.
- Internal: `self._agent: Agent[EtchDeps, RedTestSpec] = Agent(model=model or MODEL_DEFAULT, deps_type=EtchDeps, result_type=RedTestSpec, system_prompt=...)`.
- `run(*, step: str, scenario_context: dict) -> RedTestSpec`: builds prompt from step + scenario context, awaits `self._agent.run(prompt)`, returns `.output`.

`EtchStage.run_scenario` (already async from Plan 5): no signature change. Constructs `PydanticEtchAgent(model=host_config.model)` when real-model path, or a `StubEtchAgent` returning canned `RedTestSpec` when `--dry-run`.

### CosmeticItem schema

`src/mage/artifacts/cosmetic.py` (new):

```python
class CosmeticItem(BaseModel):
    sub_bid: str
    file_path: Path
    line_range: tuple[int, int]      # inclusive start, inclusive end
    replacement_text: str
    rationale: str
    proposed_by: str                  # reviewer dimension or "human"
    applied_at: datetime | None = None
    content_hash: str                # sha256(replacement_text); for idempotency
```

`tests/unit/test_cosmetic_item.py`: validates line_range ordering (start <= end), Path resolution, hash stability across runs.

### CosmeticRefiner agent

`src/mage/agents/cosmetic_refiner.py` (new):
- `CosmeticRefiner(*, model: Model | None = None)`.
- `async def refine(raw: dict, *, semaphore: asyncio.Semaphore) -> CosmeticItem`: builds prompt from raw dict, awaits LLM, parses to `CosmeticItem`.
- LLM structured-output via `Agent[CosmeticDeps, CosmeticItem]`.
- Used by `mage cosmetic apply` with `asyncio.Semaphore(host_config.max_concurrent_llm_calls)` cap (Plan 8).

### mage cosmetic apply CLI

`src/mage/cli.py`:
- New parser group: `cosmetic_subparsers = cosmetic_parser.add_subparsers(dest="cosmetic_command")`.
- `show_parser`: `mage cosmetic show <feature_id>` — load mapping, refine queue, print `CosmeticItem` table (sub_bid, file, lines, rationale).
- `apply_parser`: `mage cosmetic apply <feature_id> [--dry-run]` — refine queue, atomically edit files, commit per item on feature branch.
- New `EventType` members (in `src/mage/orchestration/events.py`): `COSMETIC_ITEM_APPLIED`, `COSMETIC_ITEM_SKIPPED` (idempotent re-apply), `COSMETIC_APPLY_FAILED`.

Cosmetic apply loop:
```
for item in refined_items:
    if item.applied_at and item.applied_at.hash == item.content_hash:
        emit SKIPPED; continue
    target = project_dir / item.file_path
    lines = target.read_text().splitlines()
    new_lines = lines[:item.line_range[0]-1] + item.replacement_text.splitlines() + lines[item.line_range[1]:]
    target.write_text("\n".join(new_lines) + "\n")  # atomic-ish for small files
    git commit -m "cosmetic(<sub_bid>): <rationale>"  # via injected command_runner
    item.applied_at = datetime.now(UTC)
    emit APPLIED
```

### mage run unlock

`src/mage/cli.py`:
- Remove `NotImplementedError` gate at line 374.
- `cmd_run(args)`: if `args.dry_run`, use stub agents (existing behavior); else use real Pydantic-AI agents.
- Pass `HostConfig.model` to each agent constructor at graph-build time.

## Data flow

### EtchAgent

```
EtchStage.run_scenario(target, scenario_context)
  → etcher = PydanticEtchAgent(model=host_config.model)
  → red = await etcher.run(step=target.step, scenario_context=scenario_context)
  → write red-test file to target.test_path
```

Errors:
- LLM call fail / timeout → raise `EtchFailed(raw_output=...)`; InspectLoop's mechanical pre-check catches it
- Structured-output validation fail → raise `EtchFailed(raw_output=...)` with the malformed output
- File write fail → standard `OSError`, halt the scenario

### Cosmetic apply

```
mage cosmetic apply <feature_id>
  → load mapping.yaml
  → refiner = CosmeticRefiner(model=host_config.model)
  → semaphore = asyncio.Semaphore(host_config.max_concurrent_llm_calls)
  → refined = await asyncio.gather(*[refiner.refine(q, semaphore=semaphore) for q in queue])
  → for item in refined:
      if already-applied: skip
      else: edit + commit + emit event
```

Errors:
- Refiner LLM fail → fall back to a stub `CosmeticItem(file_path=None, rationale=raw["text"])` flagged for manual intervention
- File missing / line_range out of range → emit `COSMETIC_APPLY_FAILED`, continue
- Git commit fail → halt; leave file in pre-apply state; surface error

## Concurrency

- `asyncio.Semaphore(host_config.max_concurrent_llm_calls)` caps refiner fan-out (Plan 8)
- File writes sequential within one apply run (deterministic)
- `EventsLog.append` + `MappingArtifact.save` use existing per-instance locks (Plan 8)

## Testing

### Unit (`tests/unit/test_etch_agent.py`)

- `test_pydantic_etch_agent_uses_test_model`: canned `RedTestSpec` via `TestModel(custom_output_args=canned)`
- `test_pydantic_etch_agent_prompt_contains_step_and_context`: capture system prompt, assert step + scenario_context present
- `test_etch_stage_uses_pydantic_agent_when_model_set`: dry-run vs real-model path

### Unit (`tests/unit/test_cosmetic_item.py`)

- `test_cosmetic_item_validates_line_range_order`: `start > end` rejected
- `test_cosmetic_item_content_hash_stable`: same `replacement_text` → same hash
- `test_cosmetic_item_path_resolution`: relative path resolved against project_dir

### Unit (`tests/unit/test_cosmetic_refiner.py`)

- `test_refiner_produces_cosmetic_item_from_raw_dict`: TestModel canned `CosmeticItem`
- `test_refiner_respects_semaphore_cap`: 7 items + `Semaphore(2)` → at most 2 concurrent refines
- `test_refiner_falls_back_to_stub_on_llm_fail`: malformed output → `CosmeticItem(file_path=None, ...)`

### Unit (`tests/unit/test_cli.py`)

- `test_cosmetic_show_dispatches`: parser routes `cosmetic show <id>` to `cmd_cosmetic_show`
- `test_cosmetic_apply_dispatches`: parser routes `cosmetic apply <id>` to `cmd_cosmetic_apply`
- `test_cosmetic_apply_dry_run_flag`: `--dry-run` skips file writes

### Feature (`tests/features/test_e2e_etch_llm.py`)

- `test_e2e_etch_stage_with_real_llm_wiring`: full EtchStage cycle with TestModel + canned output, red-test file written
- `test_e2e_inspect_loop_runs_after_etch`: EtchStage → RealizeStage → InspectLoop with LLM-wired agents

### Feature (`tests/features/test_e2e_cosmetic_apply.py`)

- `test_e2e_cosmetic_apply_writes_files_and_commits`: 3 cosmetic items applied, file diffs match, 3 commits on feature branch
- `test_e2e_cosmetic_apply_idempotent`: re-run skips already-applied items, no extra commits
- `test_e2e_cosmetic_apply_failed_event_on_missing_file`: line_range out of bounds → `COSMETIC_APPLY_FAILED` emitted, other items still apply

### Feature (`tests/features/test_e2e_mage_run_no_dry_run.py`)

- `test_e2e_mage_run_without_dry_run`: `mage run` succeeds end-to-end with real agents (gated by `HOST_MODEL_API_KEY` env var; skip in CI)

## Edge cases

- **Refiner LLM rate-limit**: gather returns partial; caller treats unrefined items as `file_path=None` stubs and emits `COSMETIC_REFINER_FALLBACK` event (new EventType).
- **Atomic file write**: small files use `write_text` directly. Large files (>1MB) need temp-then-rename (use existing pattern from `FileStatePersistence`).
- **Git commit during cosmetic apply**: use existing `command_runner` injection. Tests substitute a recording fake. Never `subprocess` directly.
- **Re-apply idempotency**: `applied_at.hash == content_hash` means the same content was applied before. Update `applied_at` only when content changes.

## Handoff

- **Future plan (post-Plan 9):** Pydantic-Graph's full async node-traversal machinery if branching scenarios are ever introduced. Plan 9 keeps `graph.py` as a linear async orchestrator (matches Plan 8).
- **Future plan:** Cosmetic application daemon — long-running service that watches `feature_cosmetic_queue` and applies items as reviewers add them. Not in Plan 9 scope.
- **Future plan:** Review-meta-aggregator (cross-feature reviewer summaries for retrospective analysis). Not in Plan 9 scope.

## Spec Self-Review

1. **Placeholder scan:** No "TBD"/"TODO". Event type names pinned (`COSMETIC_ITEM_APPLIED`, `COSMETIC_ITEM_SKIPPED`, `COSMETIC_APPLY_FAILED`, `COSMETIC_REFINER_FALLBACK`). CosmeticItem fields pinned (sub_bid, file_path, line_range, replacement_text, rationale, proposed_by, applied_at, content_hash). EtchAgent pattern pinned (mirrors RealizeAgent). All CLI subcommands pinned.
2. **Internal consistency:** Cosmetic queue stays as raw dicts in `mapping.yaml`; refinement is a runtime step. Plan 8 concurrency cap applies to refiner fan-out. Idempotency via `content_hash` matches existing `MappingArtifact.finalize` digest pattern.
3. **Scope check:** Single plan, three subsystems (EtchAgent, cosmetic pipeline, CLI unlock). Tightly coupled (cosmetic application depends on cosmetic schema; CLI unlock depends on EtchAgent). Single plan justified.
4. **Ambiguity check:** "Per-item processing" pinned to `CosmeticRefiner` LLM call producing one `CosmeticItem` per raw queue entry. "Direct edit + commit" pinned to atomic file write per item + one git commit per item on the feature branch. Backward compat pinned (`--dry-run` still works).
