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

## [0.1.0] - 2026-07-10

### Added

- Initial pipeline foundation: Base85 BID module, mapping artifact, file-state
  persistence, events log, stage node base classes, and the pydantic-graph
  skeleton.
- Mechanical verification checks and the host-project override mechanism.
- Decomposition, Plan, and Inscribe stages with their digest-pinned artifacts.
