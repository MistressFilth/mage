# mage

[![Checks](https://github.com/MistressFilth/mage/actions/workflows/check.yml/badge.svg)](https://github.com/MistressFilth/mage/actions/workflows/check.yml)

Spec-driven development pipeline: a staged engine that decomposes a feature
into behaviors, inscribes Gherkin scenarios, drives an inner TDD loop, inspects
the result, and finalizes the branch.

## Install

```bash
make init
```

## Quickstart

```bash
mage inspect show <feature-id> --project-dir <path>
mage settle run <feature-id> --disposition kept --project-dir <path>
mage cosmetic show <feature-id> --project-dir <path>
mage cosmetic apply <feature-id> --project-dir <path>
```

`mage settle run` without `--disposition` prompts for one of four dispositions:
merge locally, push and open a pull request, keep the branch, or discard it.
Discard requires typing `discard` to confirm.

## Configuration

mage resolves user directories per the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/) on Linux, and the platform's native directories on macOS and Windows.

| Role | Linux | macOS | Windows |
|------|-------|-------|---------|
| Config | `$XDG_CONFIG_HOME/mage` or `~/.config/mage` | `~/Library/Application Support/Mage` | `%LOCALAPPDATA%\Mage` |
| Data | `$XDG_DATA_HOME/mage` or `~/.local/share/mage` | `~/Library/Application Support/Mage` | `%LOCALAPPDATA%\Mage` |
| Cache | `$XDG_CACHE_HOME/mage` or `~/.cache/mage` | `~/Library/Caches/Mage` | `%LOCALAPPDATA%\Mage\Cache` |
| State | `$XDG_STATE_HOME/mage` or `~/.local/state/mage` | same as data | same as data |
| Runtime | `$XDG_RUNTIME_DIR/mage` (fallback: `<state>/mage/run`) | same | `%LOCALAPPDATA%\Mage` |

You can override any of these roots with `MAGE_XDG_*` env vars (e.g., `MAGE_XDG_CONFIG_HOME=/custom/path`). The freedesktop-spec `XDG_*` vars are also honored on macOS and Windows as an opt-in escape hatch.

### Config file

Bootstrap with:

```bash
mage config init
```

This writes a TOML file with built-in defaults to `<config>/mage/config.toml`. Subsequent invocations of `mage config init` refuse to overwrite — move the file aside first.

Inspect the effective settings:

```bash
mage config show
```

Print the resolved config path:

```bash
mage config path
```

Settings load in this order (highest priority first):

1. Explicit CLI arguments.
2. `MAGE_*` environment variables.
3. The TOML config file.
4. Baked-in defaults.

Available settings today: `log_level`, `default_provider`. Provider-specific settings (`default_model`, `base_url`, `api_key_env`, `options`) live in the `[providers.<name>]` block of the XDG config file; see `mage.toml` for per-project overrides.

### Environment variables

| Variable | Effect |
|----------|--------|
| `MAGE_LOG_LEVEL` | One of `debug`, `info`, `warning`, `error`. |
| `MAGE_XDG_DATA_HOME` | Override the user-data root. |
| `MAGE_XDG_CONFIG_HOME` | Override the user-config root. |
| `MAGE_XDG_CACHE_HOME` | Override the user-cache root. |
| `MAGE_XDG_STATE_HOME` | Override the user-state root. |
| `MAGE_XDG_RUNTIME_DIR` | Override the user-runtime root. |

## Providers

mage supports multiple model providers (Anthropic and MiniMax today). Configure providers in `~/.config/mage/config.toml`:

```toml
default_provider = "anthropic"

[providers.anthropic]
default_model = "claude-sonnet-5-20251001"
api_key_env = "ANTHROPIC_API_KEY"

[providers.minimax]
base_url = "https://api.minimax.io/anthropic"
default_model = "MiniMax-M3"
api_key_env = "MINIMAX_API_KEY"
```

Pin a per-agent model in `<project>/mage.toml`:

```toml
default_model = "claude-sonnet-5-20251001"

[agents]
inscribe = "minimax:MiniMax-M3"
realize = "minimax:MiniMax-M3"
```

Resolution precedence: env (`MAGE_MODEL_INSCRIBE`) > `mage.toml [agents]` > `mage.toml default_model` > XDG `default_provider.default_model`.

## mage.toml

Per-project config at `<project>/mage.toml`. See the design spec for the full schema.

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `default_model` | string | unset | Pinned default model for any agent that has no per-agent override. |
| `agents.<name>` | string | unset | Per-agent model pin (`inscribe`, `realize`, `etch`, `cosmetic_refiner`). Format: `<provider>:<model>` (e.g. `minimax:MiniMax-M3`). |
| `orphan_branch` | string | `feature-artifacts` | State-storage orphan-branch name. Validated: matches `^[a-zA-Z0-9._/-]+$`, length 1-200, no leading `.`, no trailing `.lock`, no `..` segments. Invalid values raise at `mage.toml` load time. |

## State Storage

mage keeps all per-project state — mapping artifacts, pipeline state, inspect journals, reviewer verdicts, settle reports, the approval-gate marker, the cosmetic-watcher PID, cosmetic-applied state, and the host-config override — on a project-local **orphan branch** rooted at `refs/mage/<orphan_branch>` (default: `refs/mage/feature-artifacts`). The orphan branch is never checked out and never appears in the working tree, so `git status` stays clean. Every read and write goes through `mage.state_store` and emits a `STATE_STORE_READ` / `STATE_STORE_WRITE` / `STATE_STORE_DELETE` event for the audit trail. Writes are atomic CASes against the ref; a single retry handles concurrent contention, and a second failure surfaces as `MageStateConflict`.

### Auto-migration from `.mage/`

Before v0.9.0, state lived under `<project_dir>/.mage/`. First-time users on v0.9.0+ see one transparent migration:

1. The first state-touching `mage` invocation calls `mage.state_migration.maybe_migrate()`.
2. Every file under `<project_dir>/.mage/` is read and written into the orphan branch; filename mapping is direct (`<project_dir>/.mage/inspect/<fid>/0.yaml` → `inspect/<fid>/0.yaml` on the orphan branch).
3. The legacy directory is renamed atomically to `<project_dir>/.mage.bak.<ts>/` (timestamp `<ts>` in `YYYYMMDDTHHMMSS`).
4. A `STATE_MIGRATED` event with `{from_path, to_ref, backup_path, file_count}` is appended to `events.jsonl`.
5. The migration marker (`_meta/.migrated`) makes the migration idempotent: subsequent runs no-op.

The `.mage.bak.<ts>/` directory is user-owned and never deleted by mage. Any code path that touches the legacy `.mage/` path after migration raises `MageStateMigrated`, with the backup timestamp in the message.

### `mage state` subcommand

| Command | Purpose |
|---|---|
| `mage state ls [<dir>]` | List entries under `<dir>` (default: branch root). One path per line. |
| `mage state show <path>` | Materialize one file to stdout via `git show refs/mage/<branch>:<path>`. |
| `mage state info` | Print branch name, current ref SHA, and file count. |
| `mage state restore [--from=<ts>]` | Restore orphan-branch state from a `.mage.bak.<ts>/` snapshot. With no `--from`, the latest backup is used. The restore is a snapshot-revert: post-migration writes are dropped; the migration marker is also reset so re-running `mage` auto-migrates the backup back into `.mage/`. |

`mage state` accepts the global `--project-dir PATH` (default: current directory), like every other `mage` subcommand.

## Running the pipeline

`mage run` executes the pipeline end-to-end against a project directory. Flags:

- `--project-dir PATH` — project directory (default: current directory).
- `--dry-run` — use stub agents (no LLM calls).
- `--feature-id <id>` — tag the run with a feature identifier. Useful for
  correlating inspect journal entries and cosmetic queue items with a
  specific feature. Empty string is rejected; omitting the flag preserves
  the default (`feature_id=""`).

There is no `--model` flag. Model selection resolves through, in precedence
order: the `MAGE_MODEL_<AGENT>` env override, the project's `mage.toml`
(`[agents]` per-agent entry, then `default_model`), the XDG default provider's
`default_model`, and finally a Pydantic-AI `TestModel` when nothing is
configured — which keeps the CLI deterministic with no credentials present.

## Cosmetic queue

`mage cosmetic show <feature-id>` refines the per-feature cosmetic queue and
prints the planned file edits. `mage cosmetic apply <feature-id>` writes the
edits and commits each one. `--dry-run` refines and emits audit events
(`COSMETIC_ITEM_SKIPPED`) without touching files or creating commits. State is
persisted at `cosmetic/cosmetic_applied.yaml` on the orphan branch
(`refs/mage/<orphan_branch>`, default `refs/mage/feature-artifacts`) so re-runs
skip sub_bids whose content hash matches the prior apply; a different hash
re-applies.

### Cosmetic queue control

The cosmetic queue can now be inspected and controlled directly.

| Command | Purpose |
|---|---|
| `mage cosmetic watch` | Long-running daemon; writes `cosmetic_watcher.pid` on the orphan branch (`refs/mage/<orphan_branch>:cosmetic_watcher.pid`). |
| `mage cosmetic unwatch` | Stop the daemon via the orphan-branch PID file (SIGTERM, escalate with `--force`). |
| `mage cosmetic list <feature_id>` | Row-per-entry table of pending cosmetic items; `--format json`. |
| `mage cosmetic show <feature_id>` | Refined output (LLM). `--raw` skips the LLM. `--journal` adds the inspect journal for the same feature. |
| `mage cosmetic apply <feature_id>` | Apply pending items to disk; `--filter sub_bid=...` narrows. |

All four commands (except `watch`) accept repeatable `--filter sub_bid=<sub_bid>` to narrow the
queue to a literal sub_bid set.

## Plan approval

When `HostConfig.require_plan_approval=True` (host config is read from the
orphan branch at `host_config.yaml`), the decomposition stage halts after
rendering `plan.md` and waits for an operator to clear the gate before the
plan is finalized. Two events mark the boundary:

- `APPROVAL_REQUESTED` — the gate has halted; a marker is on disk.
- `APPROVAL_GRANTED` — the gate cleared; the plan finalizes.

The marker file lives on the orphan branch at
`refs/mage/<orphan_branch>:approval_pending.json` and holds
`{feature_id, plan_digest, plan_path, requested_at}`. The digest binds the
marker to the exact plan content that was rendered — editing the plan invalidates
the marker.

### Resume workflow

1. The pipeline halts with `StageHalted(reason="plan_approval")`. The marker is
   written and `APPROVAL_REQUESTED` is appended to `events.jsonl`.
2. Review `<project_dir>/plan.md`. Then either:
   - **Approve.** Re-run `mage run` after the next pipeline tick — the
     gate sees the marker on the orphan branch with a matching digest,
     emits `APPROVAL_GRANTED`, and finalizes the plan. To pre-clear the
     marker for batch approval, run
     `mage state restore --from=<ts>` to revert migration, manually
     delete the legacy marker, then re-migrate. To check the marker
     location, use `mage state show approval_pending.json`.
   - **Request a revision.** Edit `plan.md`, re-run `mage run`. The new plan
     produces a new digest; the old marker is stale, so the gate overwrites it
     and re-halts with `StageHalted(reason="plan_approval_stale")`.
3. The marker is also deleted automatically when the next run finds it present
   with a matching digest — the operator can pre-write it to grant approval
   in batch, though the typical flow is the human-clear + re-run above.

### CI override

Automated runs should disable the gate at the host config:

```yaml
# host_config.yaml (read from refs/mage/<orphan_branch>:host_config.yaml)
host_config:
  require_plan_approval: false
```

With `require_plan_approval=False` the gate is a no-op: no halt, no marker, no
extra events. This is the back-compat floor; behavior is byte-identical to
pre-Plan 15 runs.

### Malformed marker

A corrupted marker (invalid JSON or unreadable) is treated as stale: the gate
overwrites it with the current digest and re-halts. No silent grant on
corrupted state.

## Development

```bash
make test    # unit + feature tests
make check   # lint, typecheck, format
make help    # all targets
```

## Repository status and policy

Repository publication and branch-protection rulesets are external to this
repo. The intended `main` policy is documented in
[AGENTS.md](AGENTS.md): protected history, pull requests, squash-only merges,
and an aggregating `check` status gate. Verify the live ruleset before
publishing because this README cannot assert the current GitHub state.

## Links

- [CHANGELOG.md](CHANGELOG.md)
- [AGENTS.md](AGENTS.md) — repository conventions for LLM agents
