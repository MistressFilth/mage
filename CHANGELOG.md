# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Plan 11: `mage cosmetic watch` long-running daemon. Tails `events.jsonl` for `MAPPING_SAVED` events; diffs the `feature_cosmetic_queue` against the last seen snapshot and auto-applies new entries per feature. Reuses Plan 10's `CosmeticAppliedState` for idempotency.
- Plan 11: `MappingArtifact.save(path, *, events_log=None)` emits `EventType.MAPPING_SAVED` when an `EventsLog` is supplied.
- Plan 11: 5 new EventTypes — `MAPPING_SAVED`, `COSMETIC_WATCHER_STARTED`, `COSMETIC_WATCHER_STOPPED`, `COSMETIC_WATCHER_APPLIED_FEATURE`, `COSMETIC_WATCHER_FAILED`.
- Plan 11: `apply_for_feature(project_dir, feature_id)` extracted to `mage.orchestration.cosmetic_apply`; reused by the watcher.
- Plan 11: `mage mapping save --project-dir PATH` CLI for explicit save-event emission (used by E2E and external hooks).
- Plan 8: asyncio concurrency for LLM-bound operations. `HostConfig.max_concurrent_llm_calls` (default 7) caps fan-out via `asyncio.Semaphore`. Inscribe reviewers run concurrently via `asyncio.gather`; InspectFeature dispatches across scenarios concurrently. Cosmetic-queue per-item parallelism is deferred to Plan 9 (no per-item LLM processing exists today).
- Plan 9: `PydanticEtchAgent` concrete implementation mirroring `PydanticRealizeAgent` plumbing; `EtchStage` swaps its injected stub for the real agent whenever `HostConfig.model` is set.
- Plan 9: `CosmeticItem` schema (sub_bid, file_path, line_range, replacement_text, rationale, proposed_by, applied_at, content_hash with sha256 idempotency hash).
- Plan 9: `CosmeticRefiner` LLM agent converts raw cosmetic-queue dicts into concrete `CosmeticItem` records; falls back to a stub (file_path=None) when the LLM errors.
- Plan 9: `mage cosmetic show <feature_id>` — refines queue and prints items as a table.
- Plan 9: `mage cosmetic apply <feature_id> [--dry-run]` — refines queue, atomically edits files, commits per item on the feature branch, and emits 4 new audit events (`COSMETIC_ITEM_APPLIED`, `COSMETIC_ITEM_SKIPPED`, `COSMETIC_APPLY_FAILED`, `COSMETIC_REFINER_FALLBACK`).
- Plan 10: `MappingArtifact.feature_cosmetic_queue` entries gain a required `feature_id` field (schema_version bumped to 2); `mage cosmetic {show,apply}` filter by feature.
- Plan 10: `CosmeticAppliedState` persists already-applied items at `.haileris/cosmetic_applied.yaml`; `mage cosmetic apply` re-runs skip already-applied sub_bids (matches by content_hash) and re-applies when content changes.
- Plan 10: 6 `test_e2e_*` cases from the Plan 9 spec landed: cosmetic apply success/idempotency/missing-file; EtchStage + InspectLoop with real LLM wiring; gated `mage run` no-dry-run smoke.
- feat(discipline): add Plan 7 Three Practices enforcement for all six Approved
  Gate Scope rules (P1-P6), revision flow, full supersession flow (v1 only),
  and the cosmetic gate.
- Etch and Realize stages driving the inner TDD loop, with carry-forward
  injection of prior-iteration findings into the next Realize prompt.
- Per-loop Inspect: mechanical pre-check plus the `IncrementQuality` reviewer,
  routing findings to one of three destinations (spec, code, cosmetic).
- End-of-feature Inspect: eight feature-scoped reviewers with three-tier
  severity routing (Critical / Important / Minor) and a digest-pinned
  `InspectArtifact`.
- Settle: readiness gate on a merge-ready `InspectArtifact`, cosmetic-queue
  hand-off, and branch finalization across four dispositions (`merged`,
  `pr_opened`, `kept`, `discarded`).
- `mage inspect show` and `mage settle run` CLI subcommands.
- `Makefile`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md`, and
  `.pre-commit-config.yaml` to bring the repository in line with the shared
  repository standards.

### Changed

- Plan 10: `PydanticEtchAgent` and `CosmeticRefiner` gain a test-mode passthrough when `model` is unset or set to the string `"test"`. The agent synthesizes a `RedTestSpec` / `CosmeticItem` directly from the call arguments without invoking the LLM. This makes `mage cosmetic apply --model test` and EtchStage runs deterministic in CI without per-call TestModel configuration. The passthrough takes precedence only when no agent has been injected by a test (existing unit tests that monkey-patch `self._agent` still win).
- Plan 10: `mage cosmetic apply` accepts `--model <id>` to override `HostConfig.model` for a single invocation (mirrors `mage run --model`). Useful for switching the cosmetic refiner between the configured model and the test passthrough without editing `mage.toml`.
- Plan 10: `mage cosmetic apply` surfaces specific failure `reason` values in `cosmetic_apply_failed` events: `"git-timeout"` when `git commit` exceeds the 30s `subprocess.TimeoutExpired` window, and `"state-save-failed"` when the post-apply idempotency-state write fails. The fallback `reason=str(e)` path is retained for any other unhandled exception.
- `PipelineGraph.run` and all `StageNode.run` methods are now async coroutines; the CLI wraps execution in `asyncio.run`. `EventsLog.append` and `MappingArtifact.save` are async and serialized via per-instance `asyncio.Lock`. `acquire_cycle_lock` and `release_cycle_lock` are async and use a per-context `asyncio.Lock`.
- Plan 9: `mage run` no longer requires `--dry-run`. The same stage graph is wired regardless of mode; per-agent stub-vs-real substitution is driven by whether `HostConfig.model` is set (default unset → stub agents; `--model` or config → Pydantic-AI agents).
- feat(orchestrator): wire StageNodes to DisciplineStage event subscriptions,
  enforce the P3 guard in AutomationStage, and acquire the cycle lock in
  InscribeStage.

### Fixed

- Plan 12: thread real `feature_id` from `mage inspect show` through `PipelineContext`, `InspectLoopStage`, and `InspectJournalEntry`. Cosmetic queue entries no longer carry the hardcoded `"unknown"` placeholder, so `mage cosmetic apply <feature-id>` and the cosmetic watcher can now correlate to the actual feature.
- Plan 12: new `INSPECT_LOOP_FEATURE_RESOLVED` event emitted on first iteration carrying `feature_id` + `scenario_id`.
- fix(discipline): make revision, supersession, and live-event handling
  idempotent and correlate approval lock release with the approved scenario.
- A failing post-merge test run no longer leaves the merge on the base branch:
  Settle records the pre-merge SHA and resets to it before re-raising.
- Merging from a host-owned worktree no longer skips cleanup silently; it emits
  a `settle_cleanup_skipped` event naming the branch and the provenance reason.
- Discard re-reads HEAD immediately before the destructive delete and refuses
  when it no longer points at the branch captured during detection.
- Failed-test event payloads truncate captured output to the last 4096 bytes
  and flag the truncation instead of embedding unbounded pytest output.
- The settle report is written before the mapping flips to `settled`, so a
  failed report write cannot leave a settled status with no record.
- `mage settle run` reports `ValueError` the same way it reports `SettleError`
  instead of surfacing a traceback.
- A conflicted `git merge` now rolls the base branch back too, not only a
  failing post-merge test run.
- A rollback that itself fails chains the original failure as its cause and
  still records `settle_merge_rolled_back` with `rollback_succeeded: false`.

## [0.1.0] - 2026-07-10

### Added

- Initial pipeline foundation: Base85 BID module, mapping artifact, file-state
  persistence, events log, stage node base classes, and the pydantic-graph
  skeleton.
- Mechanical verification checks and the host-project override mechanism.
- Decomposition, Plan, and Inscribe stages with their digest-pinned artifacts.

## [Unreleased] - Plan 6

### Added

- PipelineGraph now runs end to end: Decomposition → Inscribe → Automation (Etch → Realize → InspectLoop, nested per scenario and per increment) → InspectFeature → Settle.
- `FeatureRunner` (orchestration/runner.py): pure loop driver with no I/O of its own. Mutates only `PipelineContext.automation_cursor` and returns `list[ScenarioOutcome]`.
- `AutomationStage` (orchestration/automation.py): thin `StageNode` shim that builds `ScenarioTarget`s from approved scenarios, delegates to `FeatureRunner`, and writes outcomes back to the mapping with `SCENARIO_LIVE` emission and the `APPROVED → LIVE` transition.
- Typed frozen data-flow models: `ScenarioTarget`, `Increment`, `IncrementResult`, `ScenarioOutcome`, `AutomationCursor` (all in orchestration/runner.py).
- `mage run --dry-run --model` end-to-end. `--dry-run` substitutes stub agents; `--model` overrides `HostConfig.model`. `mage review resume` is deleted; `mage run` resumes automatically.
- `EtchStage.run_scenario`, `RealizeStage.run_increment`, `InspectLoopStage.inspect_increment` — the three automation stages are no longer `StageNode` subclasses. `InspectLoopStage` returns `InspectRoute | None` so `FeatureRunner` controls the loop.
- `HostConfig.model` field.

### Fixed

- `InspectLoopStage`'s keyword-only constructor replaced the legacy `realize_stage` parameter and dropped `StageNode` inheritance; all pre-existing call sites updated.
- The cosmetic queue now uses `MappingArtifact.append_cosmetic(CosmeticItem(...))` instead of raw dicts.
- `RealizeStage.run_increment` rebuilds the per-scenario carry-forward window (last 5 journal entries) and cross-scenario observations (last 3 from siblings) before each agent call. The previous Plan 4 implementation was deleted in Task 4 and the substitution restored.
- All four halt exceptions (`ScenarioInspectHalted`, `InspectFeatureHalted`, `ReviewBudgetExhausted`, `PlanRevisionRequired`) now route through a single `_persist_halt` path that accepts `BaseException` and uses `getattr` defaults so `PlanRevisionRequired`'s structured payload survives unchanged while `ScenarioInspectHalted` flows through with sensible defaults.

### Changed

- `ReviewerFinding` schema gains `route: InspectRoute = "code"`. The string-prefix parsing fallback (`"spec:"` / `"cosmetic:"` in `suggestion`) is deleted; the prompt now requires the structured `route` field. Default `"code"` is additive and backward-compatible.
