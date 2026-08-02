# AGENTS.md

Repository memory for LLM agents working on **mage** — the execution engine for
a spec-driven development pipeline.

## Pre-PR checklist

Before opening or merging a PR:

1. **Bump the version per SemVer.** Patch for fixes, minor for features, major
   for breaking changes. The version surfaces are `pyproject.toml` (`version`,
   PEP 440 form) and the git tag `vX.Y.Z` (SemVer form).
2. **Update `CHANGELOG.md`.** Add the entry under `[Unreleased]` in the correct
   `### Added` / `### Changed` / `### Fixed` group.
3. **Update `README.md`.** New commands, config options, install steps, and
   behavior changes all belong there.
4. **Update `docs/`.** Specs live in `docs/superpowers/specs/`, plans in
   `docs/superpowers/plans/`. A behavior change that contradicts a spec means
   the spec is edited in the same PR.

## Repository compliance

Before opening or merging a pull request, run the local checks and inspect the
tracked-content results:

```bash
make verify-repository
make check
make test
```

`make verify-repository` is read-only. It checks the required files, exact
`CLAUDE.md` references, tracked documentation directories, the changelog has
exactly one `## [Unreleased]` section, local-only ignore entries, tracked
cache artifacts, remote configuration, bare-repository layout, and worktree
upstreams. Keep `docs/superpowers/specs/` and `docs/superpowers/plans/`
tracked; do not restore a broad ignore rule for `docs/superpowers/`.

Before changing repository visibility or publishing content, scan every
tracked text file for secrets. A detected credential blocks publication until
it is revoked or rotated and the scan is clean. The intended `main` policy is
documented in @AGENTS.md rather than asserted from the in-tree state; the
live GitHub ruleset must be inspected before relying on it.

## Pre-existing issues

A "pre-existing" issue — one already on `main`, in the tracker, or marked
`TODO` / `FIXME` / `XXX` — is yours the moment you encounter it. Resolve it or
escalate it. Do not label it out-of-scope.

## Project shape

- `src/mage/artifacts/` — digest-pinned YAML artifacts (`mapping`, `plan`,
  `verdict`, `inspect`). Every artifact has `finalize()` and `load()`; `load()`
  raises on a digest mismatch.
- `src/mage/orchestration/` — pipeline stages and the pydantic-graph wiring.
  Each stage subclasses `StageNode` and emits typed events.
- `src/mage/agents/` — Pydantic-AI agents (`InscribeAgent`, `RealizeAgent`,
  `EtchAgent`).
- `src/mage/verification/` — mechanical checks, reviewers, and the host-project
  override mechanism (`HostConfig`).
- `src/mage/cli.py` — the `mage` entry point.
- `tests/unit/` — unit tests. `tests/features/` — behavior tests (`test_e2e_*`
  plus the smoke test). `tests/conftest.py` holds fixtures shared by both.

## Conventions

- **Events are the audit trail.** Any new stage outcome gets an `EventType`
  member and an emitted `Event`. A silent branch is a defect — if a code path
  declines to act, it records why.
- **Nothing shells out directly.** Stages take an injected `command_runner`;
  tests substitute a recording fake. `subprocess` appears only in the default
  runner.
- **Destructive git operations are guarded.** Worktree cleanup requires a
  `.worktrees` path component; HEAD is re-read immediately before a delete.
- **The string `haileris_v2` is forbidden** anywhere in the tree.
- Commits follow Conventional Commits. No `Co-Authored-By` trailers.

## Common tasks

See @Makefile for the full target list. The ones you will use:

```bash
make init                # set up from scratch
make test                # unit + feature tests
make check               # lint, typecheck, format
make verify-repository   # repository rules and worktree invariants
```

