# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

### Fixed

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
