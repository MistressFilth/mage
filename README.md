# mage

[![Checks](https://github.com/MistressFilth/mage/actions/workflows/check.yml/badge.svg)](https://github.com/MistressFilth/mage/actions/workflows/check.yml)

Spec-driven development pipeline: a staged engine that decomposes a feature
into behaviors, inscribes Gherkin scenarios, drives an inner TDD loop, inspects
the result, and finalizes the branch.

See `docs/superpowers/specs/` for the design documents and
`docs/superpowers/plans/` for the implementation plans.

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

## Cosmetic queue

`mage cosmetic show <feature-id>` refines the per-feature cosmetic queue and
prints the planned file edits. `mage cosmetic apply <feature-id>` writes the
edits and commits each one. `--dry-run` refines and emits audit events
(`COSMETIC_ITEM_SKIPPED`) without touching files or creating commits. State is
persisted at `.haileris/cosmetic_applied.yaml` so re-runs skip sub_bids whose
content hash matches the prior apply; a different hash re-applies.

## Plan approval

When `HostConfig.require_plan_approval=True` (in `.haileris/config.yaml`), the
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
# .haileris/config.yaml
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

Design documents and implementation plans are tracked in the repository:

- [Design documents](docs/superpowers/specs/)
- [Implementation plans](docs/superpowers/plans/)

Repository publication and branch-protection rulesets are external to this
repo. The intended `main` policy is documented in
[AGENTS.md](AGENTS.md): protected history, pull requests, squash-only merges,
and an aggregating `check` status gate. Verify the live ruleset before
publishing because this README cannot assert the current GitHub state.

## Version

The current development version is `0.3.11`.

## Links

- [CHANGELOG.md](CHANGELOG.md)
- [AGENTS.md](AGENTS.md) — repository conventions for LLM agents
