# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `make verify-repository`: read-only repository compliance checker
  (`scripts/verify_repository.py`). Asserts required files
  (`README.md`, `CHANGELOG.md`, `AGENTS.md`, `AGENTS.local.md`, `CLAUDE.md`,
  `Makefile`, `.pre-commit-config.yaml`), tracked `docs/superpowers/specs/`
  and `docs/superpowers/plans/` paths, a single `[Unreleased]` section in
  `CHANGELOG.md`, that `CLAUDE.md` contains only `@AGENTS.md\n@AGENTS.local.md`
  references, the `.gitignore` local-only entries
  (`AGENTS.local.md`, `.claude/settings.local.json`), and the absence of cache
  artifacts. Verifies the remote URL is `https://github.com/{owner}/{repo}.git`,
  the fetch refspec is `+refs/heads/*:refs/heads/*`, and the bare-repo worktree
  layout invariants (bare dir name, sibling worktrees, directory ↔ branch
  parity, no checked-out branch in the bare dir, per-worktree upstream
  tracking). Topology checks tolerate currently-active worktrees and local
  worktrees that have never pushed a remote-tracking branch.
- `.gitleaks.toml` allowlist suppressing `sha256:` package-hash false positives
  on the `uv.lock` path; gitleaks scans otherwise report every pinned package
  digest as a credential candidate.

### Changed

- Repository compliance guidance now tracks design and implementation plans in
  `docs/superpowers/{specs,plans}/` and exposes `make verify-repository` to
  enforce the on-disk requirements. Repository publication status and the live
  GitHub ruleset are not asserted in this changelog; verify them before
  relying on the policy.
- Identified stale local branches that are candidates for `git branch -D`:
  none of these branches are checked out in any worktree, none have an
  upstream configured, and they are not `worktree-agent-*` active branches.
  They have NOT been deleted by this release; they are listed here so an
  operator can prune them safely. Confirm with
  `git worktree list --porcelain` before deletion:

  ```bash
  git branch -D plan-10-cosmetic-idempotency
  git branch -D plan-11-cosmetic-watch
  git branch -D plan-13-feature-id-sentinel-cleanup
  git branch -D plan-14-settle-supersession
  ```

  Notes:

  - `plan-10-cosmetic-idempotency` and `plan-11-cosmetic-watch` are merged
    into `main` via pull requests (#1 and #2) and are safe to delete.
  - `plan-13-feature-id-sentinel-cleanup` and `plan-14-settle-supersession`
    are NOT merged into `main`; the Plan 13 / Plan 14 commits reachable from
    those branches do not appear on `main` (`git merge-base --is-ancestor`
    returns false; `git branch --contains` on the tip excludes `main`). The
    CHANGELOG `[0.3.7]` section describes the Plan 13 / Plan 14 work as if
    it shipped, but the corresponding code changes never landed. Deleting
    these branches orphans that work; first verify whether the work should
    be merged, cherry-picked, or marked intentionally abandoned before
    running the deletion command.

- `InspectFeatureStage` is no longer a `StageNode` subclass. The class is a
  feature-level service whose sole public entry is `run_pass(context, *,
  feature_id, scenarios, iteration=None) -> InspectArtifactContent`. The
  unimplemented `_run` method has been deleted. The
  `InspectFeatureHalted` propagation path and `graph.py`'s halt handler are
  unchanged.
- Lint and typecheck baseline cleanup (Plan 19): `make check` is now green.
  Resolved the pre-existing ruff baseline (BLE001, B017, C408, F821, F841,
  PLW1510, RUF012, RUF059, SIM118, S110, S112, TRY004) and the
  pre-existing pyright baseline (reportAbstractUsage, reportArgumentType,
  reportAssignmentType, reportAttributeAccessIssue, reportCallIssue,
  reportIncompatibleMethodOverride, reportInvalidTypeVarUse,
  reportReturnType, reportUndefinedVariable). Also removed 3 dead-code items:
  `EventType.SCENARIO_HALT_PERSISTED` (declared, never emitted),
  `CosmeticPatch.applied_at` (written, never read) plus `CosmeticApplied.applied_at`
  (required, never set), and the 3 duplicate `InspectRoute = Literal[...]`
  declarations (now one canonical declaration in `mage.artifacts.inspect`).
  A new static-guard test (`tests/unit/test_static_guards_lint_baseline.py`)
  prevents future regression of the gate.
- Replaced `pyright` with [`ty`](https://github.com/astral-sh/ty) as the
  `make typecheck` driver. `ty` is Astral's Python typechecker (Rust
  implementation, very fast) and is a drop-in for the `pyright` rule subset
  we relied on. The `[tool.pyright]` block was removed from `pyproject.toml`
  (no equivalent `[tool.ty]` is required — `ty` auto-detects `src/` layout
  from the project root). The `scripts/` path is currently reachable by
  pytest only (via `[tool.pytest.ini_options] pythonpath = ["src", "scripts"]`),
  so the three `from verify_repository import ...` sites in
  `tests/unit/test_verify_repository.py` carry in-line
  `# ty: ignore[unresolved-import]` suppressions; an inline `[tool.ty]`
  block can replace these once we add a real `scripts/` package.
  `make typecheck` now invokes `uv run ty check src tests scripts` and the
  static-guard test (`tests/unit/test_static_guards_lint_baseline.py`) was
  re-pointed at the same command so the gate keeps enforcing zero
  typecheck errors. A handful of `pyright: ignore[reportIncompatibleMethodOverride]`
  / `type: ignore[union-attr]` comments were updated to `ty: ignore[...]`
  where the rule names diverge; test stub assignments gained combined
  `# type: ignore[arg-type, ty:invalid-argument-type]` annotations so
  pyright and `ty` both accept them. The lazy `_save_lock` write in
  `MappingArtifact._get_save_lock` now goes through `object.__setattr__`
  to satisfy `ty`'s read-only-property check (the underlying
  `pydantic.BaseModel(frozen=True)` model still enforces the
  `ValidationError` contract for any user-side write).

### Fixed

- `RealizeStage` journal windows (`per_scenario_window`, `cross_scenario_window`) now honor `HostConfig` — was hardcoded module constants, silently ignored from `.haileris/config.yaml`.

## [0.3.9] - 2026-08-02

### Added

- Repository rules compliance design document at
  `docs/superpowers/specs/2026-08-02-repository-rules-compliance-design.md`
  outlining the compliance baseline, invariants, and enforcement strategy.
- Repository rules compliance implementation plan at
  `docs/superpowers/plans/2026-08-02-repository-rules-compliance.md`
  describing the verifier rollout phases and test coverage.

### Fixed

- `make verify-repository`: address review findings, harden assertions, and
  correct enforcement gaps surfaced during code review. Tightened the Makefile
  `verify-repository` target wiring, pyproject script entrypoint, and the
  verifier's invariant assertions; expanded
  `tests/unit/test_verify_repository.py` to cover the additional cases.

## [0.3.7] - 2026-08-01

### Changed

- Renamed `mage.artifacts.inspect.CosmeticItem` to `CosmeticFinding` and `mage.artifacts.cosmetic.CosmeticItem` to `CosmeticPatch` to remove the longstanding name collision. The two classes remain distinct shape-wise; this is a pure rename. `MappingArtifact.append_cosmetic` is now `append_cosmetic_finding`; the `feature_cosmetic_queue` Python attribute is now `cosmetic_findings` (the on-disk YAML/JSON key is preserved via a Pydantic alias, so existing mapping artifacts still load). `guard_cosmetic_application` now takes a `sub_bid: str` directly instead of a full `CosmeticFinding`. A static guard test (`tests/unit/test_static_guards_cosmetic_rename.py`) prevents regression of the bare `CosmeticItem` name in `src/`.

### Fixed

- `InspectFeatureStage._run_reviewers` now honors `HostConfig.enabled_reviewers`.
  Previously the field was inert on the inspect path; the filter now excludes
  both scenario and cross-scenario reviewers not listed in the config. Semantics
  match `InscribeStage`: `None` = all enabled, `[]` = none, explicit list =
  subset. Fixes the inert-field gap tracked in the TODO backlog.
- Approval gate placeholder closed: `require_plan_approval=True` now halts the
  pipeline via `APPROVAL_REQUESTED` + `StageHalted`, persists a digest-bound
  marker at `.mage/approval_pending.json`, and finalizes the plan on the next
  run (emitting `APPROVAL_GRANTED`) instead of warning + auto-approving.
- Plan 13 (feature_id sentinel cleanup): removed the three remaining hardcoded `feature_id="unknown"` literals that Plan 12 left at `inspect_feature.py:377`, `inscribe.py:69`, and `inscribe.py:362`. `InspectFeatureStage._append_cosmetics` now accepts a `feature_id` kwarg threaded from `_run_iteration`; `InscribeStage._run` reads `context.feature_id` for both `INSCRIBE_STARTED` and `INSCRIBE_COMPLETED` payload values. Empty-string default is preserved (Plan 12 default); no `"unknown"` fallback is ever substituted. `MappingArtifact._validate_cosmetic_queue` now accepts an empty-string `feature_id` on load (Plan 13 invariant that empty-string values round-trip without raising). The strict "key omitted" validation from Plan 10 is preserved — only the empty-string case was relaxed. New `tests/features/test_e2e_feature_id_sentinel_cleanup.py` adds a Python-regex static guard (catches single-line and wrapped-across-lines regressions) and an end-to-end driver that asserts no emitted event or cosmetic-queue entry ever carries the sentinel.
- Plan 14 (settle supersession event): wired `Settle.run_settle` to emit `SCENARIO_SUPERSESSION_REQUESTED` per scenario tagged for the settled feature whose `supersedes` field is set. The downstream `discipline/stage.py:105` handler (already implemented in Plan 7) now finally runs `begin_supersession` end-to-end for the first time; `complete_supersession` follows on `SCENARIO_LIVE`. Schema: added optional `ScenarioEntry.feature_id: str | None = None` (legacy default `None`). Inscribe threads `context.feature_id` onto appended scenarios. Settle skips emission when `disposition == "discarded"`. Static-guard net keeps the placeholder out (`grep "TODO(plan8)" src/mage` returns zero matches).

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
