# AGENTS.md

Repository memory for LLM agents working on **mage** — the execution engine for
a spec-driven development pipeline.

## Pre-PR checklist

Before opening or merging a PR:

1. **Bump the version per SemVer.** Patch for fixes, minor for features, major
   for breaking changes — but while the project is pre-1.0, a breaking change
   rides a minor bump rather than declaring 1.0.0. The version surfaces are
   `pyproject.toml` (`version`, PEP 440 form) and the git tag `vX.Y.Z` (SemVer
   form). Do not add a third: `mage.__version__` derives from installed package
   metadata via `importlib.metadata`, so `pyproject.toml` stays the only place
   a version literal is written.
2. **Update `CHANGELOG.md`.** Add the entry under `[Unreleased]` in the correct
   `### Added` / `### Changed` / `### Fixed` group.
3. **Update `README.md`.** New commands, config options, install steps, and
   behavior changes all belong there.

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
- `src/mage/xdg.py` — XDG root resolution chain (`MAGE_XDG_*` → `XDG_*` → `platformdirs`).
- `src/mage/paths.py` — App directory composition (`<root>/mage/<role>`).
- `src/mage/settings.py` — pydantic-settings substrate with TOML config file and `MAGE_*` env chain.
- `src/mage/cli.py` — the `mage` entry point.
- `tests/unit/` — unit tests. `tests/features/` — behavior tests (`test_e2e_*`
  plus the smoke test). `tests/conftest.py` holds fixtures shared by both.
- `.pre-commit-config.yaml` — local hooks delegate to `make` targets (`make lint`,
  `make typecheck`, `make format`, `make test`); installed by `make init`.
- `.github/workflows/check.yml` — `matrix-check` (ubuntu/macos/windows) +
  aggregating `check` job that produces the branch-protection-required status
  context. The aggregating job is required because a matrix job reports as
  `check (<os>)` and would not satisfy the ruleset's exact-context requirement.

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
- Configuration flows through `mage.settings.load_settings()`. Direct `os.environ` reads outside `xdg.py` / `settings.py` / `cli.py` / `cli_config.py` are forbidden (enforced by `tests/unit/test_static_guards_p30.py`).
- Commits run the local pre-commit hooks (lint, typecheck, format, test). `git commit --no-verify` is allowed but CI re-runs `pre-commit run --all-files` against every push and PR to catch bypassed commits.
- Commits follow Conventional Commits. No `Co-Authored-By` trailers.

## Common tasks

See @Makefile for the full target list. The ones you will use:

```bash
make init                # set up from scratch
make test                # unit + feature tests
make check               # lint, typecheck, format
```

