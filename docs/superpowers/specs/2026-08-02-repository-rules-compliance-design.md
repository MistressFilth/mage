# Repository Rules Compliance Design

**Date:** 2026-08-02
**Status:** Approved

## Goal

Bring `mage` into compliance with all shared repository rules, including tracked repository files, local verification, bare-repository worktree topology, and GitHub branch protection. Change `MistressFilth/mage` from private to public because GitHub rulesets are unavailable for the current private user-owned repository tier.

## Scope

- Keep the bare Git repository and sibling worktree layout.
- Move nested stale worktrees into sibling directories named after branches after checking active processes.
- Preserve uncertain or active worktrees; never delete branches or worktrees automatically.
- Repair branch upstreams only when matching remote branches exist.
- Add required local-only ignore entries.
- Track `docs/superpowers/specs/` and `docs/superpowers/plans/` instead of ignoring them.
- Update README, AGENTS, CHANGELOG, and version surfaces.
- Add deterministic local repository verification tooling and a Make target.
- Secret-scan tracked content before changing repository visibility.
- Change repository visibility to public only after a clean scan.
- Create and verify a `main` GitHub ruleset.

## Repository content

`.gitignore` will include `AGENTS.local.md` and `.claude/settings.local.json`. `AGENTS.local.md` remains local-only and is not committed. `CLAUDE.md` remains exactly `@AGENTS.md` and `@AGENTS.local.md` on separate lines.

`docs/superpowers/specs/` and `docs/superpowers/plans/` become tracked documentation paths. README links and AGENTS instructions will describe their purpose and verification workflow. `CHANGELOG.md` will have one `[Unreleased]` section. `pyproject.toml` will receive a patch bump from `0.3.9` to `0.3.10`; all release-facing documentation will match.

## Local verification

Add `scripts/verify_repository.py`, a read-only checker. It verifies:

- required files and exact `CLAUDE.md` references;
- required ignore entries;
- SemVer version surface;
- repository remote URL and direct fetch refspec;
- bare repository state;
- sibling worktree paths, branch/path agreement, and matching `origin/<branch>` upstreams;
- absence of forbidden tracked artifacts.

Add `make verify-repository`. The checker exits nonzero with concise actionable diagnostics. It does not mutate Git state or files.

## Worktree migration

Inventory worktrees, branches, upstreams, and process activity first. Move safe nested worktrees to repository siblings with matching branch names. Preserve source and branch when a move fails. Do not guess missing remote branches or remove stale worktrees automatically. Run the verifier after every migration batch.

## GitHub protection

Run secret scanning over tracked files before publication. A detected credential blocks publication. After a clean scan, change repository visibility to public, verify visibility, then create a `main` ruleset with:

- deletion blocked;
- non-fast-forward updates blocked;
- required linear history;
- pull request required;
- squash-only merge;
- zero required human approvals;
- required `check` status context;
- administrator bypass disabled where supported.

Verify the returned ruleset rather than trusting request payloads. Report unsupported fields exactly.

## Safety and failure handling

No visibility change occurs after a failed secret scan. No uncertain worktree is deleted or moved. Missing remote branches produce warnings without guessed configuration. GitHub failures leave local repository changes intact and report the exact API error. Verification must pass before completion claims.

## Tests and validation

Run:

```bash
make verify-repository
make check
make test
```

Also run Git worktree/upstream checks, GitHub metadata and ruleset verification, and tracked-content secret scanning. Add unit coverage for the repository verifier and static checks for required files and ignore entries.
