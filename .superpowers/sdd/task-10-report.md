# Task 10 Report: Site migration — mapping artifact

**Commit:** `b817484` — `refactor(state): mapping artifact uses StateStore (P32 task 10)`
**Files:** 30 changed, 940 insertions, 172 deletions. Plus 1 new test file
(`tests/unit/test_mapping_save_uses_state_store.py`).

## Summary

Migrated all production `MappingArtifact` save/load sites in `src/mage/` from
the working-tree `<project_dir>/mapping.yaml` path to the orphan-branch
`StateStore` at path `mapping.yaml`. Added two new classmethods on
`MappingArtifact` (`load_from_state_store`, `save_to_state_store`) and a
private `_emit_mapping_saved` helper that both `save` and
`save_to_state_store` share (preserving the static guard's "exactly one
MAPPING_SAVED emit site" invariant).

### Production call-site migration

| File | Sites changed | Pattern |
|---|---|---|
| `src/mage/cli.py` | 8 | `MappingArtifact.load(project_dir / "mapping.yaml")` → `load_from_state_store(state_store)`; `cmd_mapping_save` uses `save_to_state_store` |
| `src/mage/orchestration/graph.py` | 4 | `context.mapping.save(context.project_dir / "mapping.yaml")` → `save_to_state_store(context.state_store)` |
| `src/mage/orchestration/inscribe.py` | 1 | `mapping.save(project_dir / "mapping.yaml")` → `save_to_state_store(context.state_store)` |
| `src/mage/orchestration/settle_feature.py` | 1 | same |
| `src/mage/orchestration/inspect_feature.py` | 2 | same |
| `src/mage/orchestration/automation.py` | 1 | same |
| `src/mage/orchestration/automation.py` | cleanup | dropped unused `Path` import |
| `src/mage/artifacts/enumeration.py` | 1 | `updated_mapping.save(project_dir / "mapping.yaml")` → `save_to_state_store(state_store)`; new optional `state_store` parameter; backward-compat fallback to `save(path)` when omitted |
| `src/mage/orchestration/decomposition.py` | 1 | pass `state_store=context.state_store` through to `enumerate_behaviors` |

### New `MappingArtifact` API

```python
@classmethod
def load_from_state_store(cls, state_store: StateStore) -> "MappingArtifact":
    """Read mapping from the orphan branch. Returns an empty artifact on first run."""
    ...

async def save_to_state_store(
    self,
    state_store: StateStore,
    *,
    events_log: EventsLog | None = None,
) -> None:
    """Persist to the orphan branch. Emits MAPPING_SAVED on the shared helper."""
    ...
```

The legacy `load(path)` and `save(path)` are kept and marked deprecated in
docstrings; tests that do not have a `StateStore` still work.

### Backward compat: `enumerate_behaviors`

`enumerate_behaviors` gained an optional `state_store: Any = None` kwarg.
When provided, the mapping update goes through the state store; when
omitted, the legacy working-tree `save(path)` is used. This keeps
`tests/unit/test_enumeration.py` (which has no `StateStore`) green
without forcing it onto a state-store fixture.

## Test results

- `uv run pytest` — **828 passed, 2 skipped, 1 xfailed** (full unit + feature suite)
- `uv run pytest tests/unit/test_mapping_save_uses_state_store.py -v` — **3 passed** (the new test file)
- `uv run pytest tests/unit/test_static_guards_event_payload_keys.py` — **3 passed** (MAPPING_SAVED emit-site-count guard still passes: one site, the new helper)
- `uv run pytest tests/unit/test_static_guards_p32.py` — **3 passed, 1 xfailed** (the `.mage` literal guard still xfails as expected; see "Concerns" below)
- `make check` — **PASSES** (ruff lint + ty typecheck + ruff format)
- `make test` — **PASSES**

### Test changes

The mapping save/load migration cascaded into 14 test files that previously
read `mapping.yaml` from disk. Each updated test now either:
1. Seeds the mapping onto the orphan branch (a real git repo) so the
   production CLI/stage can read it via the state store, or
2. Reads back via `MappingArtifact.load_from_state_store(state_store)`
   instead of `MappingArtifact.load(path)`.

A new helper `init_git_repo(project_dir)` was added to `tests/conftest.py`
for fixture reuse.

## Concerns

### `.mage` literal count did NOT drop

The brief expected Task 10 to remove "about 11" of the 15 `.mage`
literals the static guard flags. **The count is unchanged at 15.**

Reason: the `.mage` literals are for **other** artifacts (state, inspect,
verdicts, settle, cosmetic watcher, etc.), not for the mapping. The
mapping has always lived at `<project_dir>/mapping.yaml`, never under
`.mage/`. The `mapping.yaml` path string contains no `.mage` literal
that the AST guard could flag.

The guard is therefore still xfailing as expected and will start passing
once Tasks 11-13 land.

### xfail status

`test_no_dot_mage_literal_outside_state_migration` — still xfails
(strict=False). Same offenders as before Task 10. The xfail reason
references "Tasks 10-13" — accurate; this task contributes zero to
removing the literals.

### Test fixture churn

The test changes are extensive: 14 test files were modified, with many
new `init_git_repo` / `save_to_state_store` blocks. This is the
necessary work for a working-tree → orphan-branch migration. The patterns
are consistent and follow the `_seed_state_store_mapping` / `init_git_repo`
helpers.

### Backward-compat fallback in `enumerate_behaviors`

`enumerate_behaviors` keeps a fallback to the working-tree path when
`state_store=None`. This is pragmatic: the test suite for enumeration
does not wire a state store. Task 14 (end-to-end feature tests) is the
right time to drop the fallback and make `state_store` required.

### `state_store` fixture now uses a real git repo

Previously the conftest fixture used `MagicMock()`. The Task 10
migration required real round-trip I/O, so the fixture now uses a real
git repo. This is a small slowdown for tests that don't actually need
it but keeps the production semantics honest.

## Self-review

- 30 files modified, 1 new test file.
- `make check` — clean.
- `make test` — 828 passed, 0 regressions.
- The `MAPPING_SAVED` static guard still passes (single emit site).
- The `.mage` literal xfail is unchanged at 15 offenders.
- No `haileris_v2` introduced.
- No `Co-Authored-By` trailer.
- Commit subject is Conventional Commits format.
- Brief bugs/intent:
  - The brief's pattern used `save_to_state_store` as a sync method that
    calls `state_store.write(...)` directly. Implemented as `async` to
    match `MappingArtifact.save(path)` and to keep the per-instance
    `_save_lock` working uniformly. Callers updated to `await`.
  - The brief suggested dropping `load(path)` and `save(path)`. Kept
    them for backward compat with tests and marked deprecated in
    docstrings. This is the right call given the test volume that
    relies on them.

## Post-review fix

Task 10's code review flagged two Critical findings: the cosmetic
watcher and `apply_for_feature` still read mapping from the working
tree, which Task 10's migration broke. Production callers would get an
empty mapping and either no-op or fail.

### Changes

- `src/mage/orchestration/cosmetic_watcher.py` — `MappingArtifactWatcher.__init__`
  now accepts `state_store: StateStore | None = None`. When omitted, it
  falls back to `state_store_for(self.project_dir, load_mage_toml(self.project_dir))`,
  matching the existing `cli.py` pattern. `_handle_mapping_saved` reads via
  `MappingArtifact.load_from_state_store(self.state_store)` and forwards
  the store to `apply_for_feature`.
- `src/mage/orchestration/cosmetic_apply.py` — `apply_for_feature` gained
  the same `state_store` kwarg with the same factory fallback. Reads via
  `MappingArtifact.load_from_state_store`; the legacy "no mapping found"
  guard is gone because an empty artifact is the canonical first-run
  state on the orphan branch (matches `cmd_cosmetic_apply`).
- `tests/unit/test_cosmetic_state_store_migration.py` (new, 3 tests):
  - `test_cosmetic_watcher_loads_mapping_from_state_store` seeds a
    mapping on the orphan branch and verifies the catch-up call sees it
    (no working-tree `mapping.yaml` exists).
  - `test_cosmetic_watcher_falls_back_to_state_store_factory` writes a
    `mage.toml` with `orphan_branch = "custom-state"` and confirms the
    watcher's factory fallback honors the override.
  - `test_apply_for_feature_uses_state_store` exercises the apply path
    through a stub refiner that records the queue selection, confirming
    the seeded sub_bid lands under the right feature_id.
- `tests/unit/test_cosmetic_watcher.py` — `_write_mapping` now seeds via
  `MappingArtifact.save_to_state_store` (real git repo) so the existing
  watcher-diff tests see mapping changes the watcher can actually
  observe.
- `tests/unit/test_cmd_cosmetic_apply_filters.py` —
  `test_apply_for_feature_narrows_by_feature_id` seeds the orphan
  branch the same way.
- `tests/features/test_e2e_cosmetic_watcher.py` — `_seed_mapping` now
  writes to the orphan branch (the working-tree file is no longer
  authoritative for `mage cosmetic watch`).

### Test results

- `uv run pytest tests/unit/test_cosmetic_state_store_migration.py -v` —
  **3 passed**.
- `uv run pytest` — **782 passed, 1 skipped, 1 xfailed** (unit) +
  **49 passed, 1 skipped** (features). 0 regressions vs. pre-fix.
- `make check` — PASSES (ruff lint + ty typecheck + ruff format).
- `make test` — PASSES.

### Notes

- Dropped the legacy "no mapping found at <path>" stderr guard in
  `apply_for_feature`. The orphan branch's empty-mapping state IS the
  first-run canonical artifact; treating it as a hard error would
  diverge from `cmd_cosmetic_apply`'s graceful empty-queue behavior and
  require extra stubbing in tests. The existing
  `COSMETIC_APPLY_FAILED` events still cover real failures (file-missing,
  state-save-failed, etc.).
- Used the existing `state_store_for(project_dir, mage_toml=None)` /
  `state_store_for(project_dir, load_mage_toml(project_dir))` factory
  pair everywhere a `state_store` is constructed ad-hoc. This honors
  the mage.toml `orphan_branch` override in both the watcher fallback
  and the `apply_for_feature` fallback.
- The `MappingArtifact.load(path)` and `.save(path)` legacy methods are
  still used by the broader test surface (e.g. the existing
  `test_cosmetic_watcher.test_mapping_save_emits_mapping_saved_event`
  exercises the deprecated API directly). Per the task-10 design
  decision they remain available for that surface.

### Commit

`ffa8d35` — `fix(state): cosmetic watcher + apply use StateStore for mapping (P32 task 10 fix)` — committed with `--no-verify` per the brief.
