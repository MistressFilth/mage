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

Available settings today: `log_level`, `host_model_api_key`. Provider model selection and per-subagent overrides arrive in a future release.

### Environment variables

| Variable | Effect |
|----------|--------|
| `MAGE_LOG_LEVEL` | One of `debug`, `info`, `warning`, `error`. |
| `MAGE_HOST_MODEL_API_KEY` | API key for the host model provider. Treated as a secret. |
| `MAGE_XDG_DATA_HOME` | Override the user-data root. |
| `MAGE_XDG_CONFIG_HOME` | Override the user-config root. |
| `MAGE_XDG_CACHE_HOME` | Override the user-cache root. |
| `MAGE_XDG_STATE_HOME` | Override the user-state root. |
| `MAGE_XDG_RUNTIME_DIR` | Override the user-runtime root. |

## Running the pipeline

`mage run` executes the pipeline end-to-end against a project directory. Flags:

- `--project-dir PATH` — project directory (default: current directory).
- `--dry-run` — use stub agents (no LLM calls).
- `--model <id>` — override the LLM model identifier.
- `--feature-id <id>` — tag the run with a feature identifier. Useful for
  correlating inspect journal entries and cosmetic queue items with a
  specific feature. Empty string is rejected; omitting the flag preserves
  the default (`feature_id=""`).

## Cosmetic queue

`mage cosmetic show <feature-id>` refines the per-feature cosmetic queue and
prints the planned file edits. `mage cosmetic apply <feature-id>` writes the
edits and commits each one. `--dry-run` refines and emits audit events
(`COSMETIC_ITEM_SKIPPED`) without touching files or creating commits. State is
persisted at `.mage/cosmetic_applied.yaml` so re-runs skip sub_bids whose
content hash matches the prior apply; a different hash re-applies.

### Cosmetic queue control

The cosmetic queue can now be inspected and controlled directly.

| Command | Purpose |
|---|---|
| `mage cosmetic watch` | Long-running daemon; writes a PID file at `<project>/.mage/cosmetic_watcher.pid`. |
| `mage cosmetic unwatch` | Stop the daemon via the PID file (SIGTERM, escalate with `--force`). |
| `mage cosmetic list <feature_id>` | Row-per-entry table of pending cosmetic items; `--format json`. |
| `mage cosmetic show <feature_id>` | Refined output (LLM). `--raw` skips the LLM. `--journal` adds the inspect journal for the same feature. |
| `mage cosmetic apply <feature_id>` | Apply pending items to disk; `--filter sub_bid=...` narrows. |

All four commands (except `watch`) accept repeatable `--filter sub_bid=<sub_bid>` to narrow the
queue to a literal sub_bid set.

## Plan approval

When `HostConfig.require_plan_approval=True` (in `.mage/config.yaml`), the
decomposition stage halts after rendering `plan.md` and waits for an operator
to clear the gate before the plan is finalized. Two events mark the boundary:

- `APPROVAL_REQUESTED` — the gate has halted; a marker is on disk.
- `APPROVAL_GRANTED` — the gate cleared; the plan finalizes.

The marker file lives at `<project_dir>/.mage/approval_pending.json` and holds
`{feature_id, plan_digest, plan_path, requested_at}`. The digest binds the
marker to the exact plan content that was rendered — editing the plan invalidates
the marker.

### Resume workflow

1. The pipeline halts with `StageHalted(reason="plan_approval")`. The marker is
   written and `APPROVAL_REQUESTED` is appended to `events.jsonl`.
2. Review `<project_dir>/plan.md`. Then either:
   - **Approve.** Delete the marker (`rm <project_dir>/.mage/approval_pending.json`)
     and re-run `mage run`. The next run sees the marker absent, finds a prior
     `APPROVAL_REQUESTED` for the same digest in `events.jsonl`, emits
     `APPROVAL_GRANTED`, and finalizes the plan.
   - **Request a revision.** Edit `plan.md`, re-run `mage run`. The new plan
     produces a new digest; the old marker is stale, so the gate overwrites it
     and re-halts with `StageHalted(reason="plan_approval_stale")`.
3. The marker is also deleted automatically when the next run finds it present
   with a matching digest — the operator can pre-write it to grant approval
   in batch, though the typical flow is the human-clear + re-run above.

### CI override

Automated runs should disable the gate at the host config:

```yaml
# .mage/config.yaml
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
