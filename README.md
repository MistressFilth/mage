# mage

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
```

`mage settle run` without `--disposition` prompts for one of four dispositions:
merge locally, push and open a pull request, keep the branch, or discard it.
Discard requires typing `discard` to confirm.

## Development

```bash
make test    # unit + feature tests
make check   # lint, typecheck, format
make help    # all targets
```

## Links

- [CHANGELOG.md](CHANGELOG.md)
- [AGENTS.md](AGENTS.md) — repository conventions for LLM agents
