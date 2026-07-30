"""SettleFeature stage: readiness gate and branch finalization."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import Callable

from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig

CommandRunner = Callable[..., CompletedProcess[str]]
_VALID_DISPOSITIONS = {"merged", "pr_opened", "kept", "discarded"}
_MAX_CAPTURED_OUTPUT = 4096


class SettleError(Exception):
    """Base exception for Settle finalization failures."""


class SettleNotReadyError(SettleError):
    """Raised when no digest-verified, merge-ready Inspect artifact exists."""


class SettleTestsFailed(SettleError):
    """Raised when the configured test command fails."""


class SettleCommandFailed(SettleError):
    """Raised when a git or GitHub finalization command fails."""


class SettleUnsafeCleanupError(SettleError):
    """Raised when cleanup would remove a non-project-owned worktree."""


@dataclass(frozen=True)
class GitEnvironment:
    """Resolved repository/worktree details used by finalization actions."""

    git_dir: Path
    common_dir: Path
    worktree_root: Path
    repo_root: Path
    branch: str
    is_worktree: bool


def _default_command_runner(
    command: list[str],
    *,
    cwd: Path,
) -> CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class SettleFeatureStage(StageNode):
    """Validate Inspect readiness, hand off cosmetics, and finalize the branch."""

    name = "settle_feature"

    def __init__(
        self,
        events_log: EventsLog,
        *,
        command_runner: CommandRunner | None = None,
        host_config: HostConfig | None = None,
        feature_id: str | None = None,
        disposition: str | None = None,
    ) -> None:
        super().__init__(events_log)
        self.command_runner = command_runner or _default_command_runner
        self.host_config = host_config or HostConfig()
        self.feature_id = feature_id
        self.disposition = disposition

    def _run(self, context: PipelineContext) -> PipelineContext:
        if self.feature_id is None or self.disposition is None:
            raise ValueError(
                "SettleFeatureStage graph execution requires feature_id and "
                "disposition constructor arguments"
            )
        self.run_settle(
            context,
            feature_id=self.feature_id,
            disposition=self.disposition,
        )
        return context

    @staticmethod
    def _latest_inspect_path(project_dir: Path, feature_id: str) -> Path:
        inspect_dir = project_dir / ".haileris" / "inspect" / feature_id
        if not inspect_dir.exists():
            raise SettleNotReadyError(
                f"No InspectArtifact directory for feature {feature_id!r}"
            )
        candidates: list[tuple[int, Path]] = []
        for path in inspect_dir.glob("*.yaml"):
            try:
                candidates.append((int(path.stem), path))
            except ValueError:
                continue
        if not candidates:
            raise SettleNotReadyError(
                f"No InspectArtifact iterations for feature {feature_id!r}"
            )
        return max(candidates, key=lambda item: item[0])[1]

    def _load_ready_inspect(
        self,
        context: PipelineContext,
        feature_id: str,
    ) -> InspectArtifactContent:
        path = self._latest_inspect_path(context.project_dir, feature_id)
        content = InspectArtifact.load(path, context.events_log)
        if content.feature_id != feature_id:
            raise SettleNotReadyError(
                f"InspectArtifact feature_id {content.feature_id!r} does not match "
                f"requested feature {feature_id!r}"
            )
        if not content.ready_to_merge:
            raise SettleNotReadyError(
                f"InspectArtifact {path} is not ready to merge"
            )
        return content

    def _run_checked(
        self,
        command: list[str],
        *,
        cwd: Path,
    ) -> CompletedProcess[str]:
        result = self.command_runner(list(command), cwd=Path(cwd))
        if result.returncode != 0:
            raise SettleCommandFailed(
                f"command failed ({result.returncode}): {' '.join(command)}\n"
                f"{result.stderr or result.stdout}"
            )
        return result

    @staticmethod
    def _truncate(output: str) -> tuple[str, bool]:
        """Keep the tail of a captured stream — failures live at the end."""
        if len(output) <= _MAX_CAPTURED_OUTPUT:
            return output, False
        return output[-_MAX_CAPTURED_OUTPUT:], True

    def _run_tests(
        self,
        *,
        feature_id: str,
        cwd: Path,
        phase: str,
    ) -> None:
        command = list(self.host_config.test_runner_command)
        result = self.command_runner(command, cwd=Path(cwd))
        if result.returncode == 0:
            return
        stdout, stdout_truncated = self._truncate(result.stdout or "")
        stderr, stderr_truncated = self._truncate(result.stderr or "")
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_TESTS_FAILED,
                payload={
                    "feature_id": feature_id,
                    "phase": phase,
                    "command": command,
                    "returncode": result.returncode,
                    "stdout": stdout,
                    "stdout_truncated": stdout_truncated,
                    "stderr": stderr,
                    "stderr_truncated": stderr_truncated,
                },
            )
        )
        raise SettleTestsFailed(
            f"Settle tests failed during {phase}: {' '.join(command)}"
        )

    @staticmethod
    def _resolved_git_path(raw: str, *, cwd: Path, label: str) -> Path:
        value = raw.strip()
        if not value:
            raise SettleCommandFailed(f"git returned an empty {label}")
        path = Path(value)
        if not path.is_absolute():
            path = cwd / path
        return path.resolve()

    def _detect_environment(self, project_dir: Path) -> GitEnvironment:
        git_dir_result = self._run_checked(
            ["git", "rev-parse", "--git-dir"],
            cwd=project_dir,
        )
        common_dir_result = self._run_checked(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=project_dir,
        )
        root_result = self._run_checked(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_dir,
        )
        branch_result = self._run_checked(
            ["git", "branch", "--show-current"],
            cwd=project_dir,
        )
        git_dir = self._resolved_git_path(
            git_dir_result.stdout,
            cwd=project_dir,
            label="git-dir",
        )
        common_dir = self._resolved_git_path(
            common_dir_result.stdout,
            cwd=project_dir,
            label="git-common-dir",
        )
        worktree_root = self._resolved_git_path(
            root_result.stdout,
            cwd=project_dir,
            label="repository root",
        )
        return GitEnvironment(
            git_dir=git_dir,
            common_dir=common_dir,
            worktree_root=worktree_root,
            repo_root=common_dir.parent,
            branch=branch_result.stdout.strip(),
            is_worktree=git_dir != common_dir,
        )

    @staticmethod
    def _safe_worktree_cleanup(environment: GitEnvironment) -> bool:
        return environment.is_worktree and ".worktrees" in environment.worktree_root.parts

    def _require_feature_branch(self, environment: GitEnvironment) -> str:
        if not environment.branch:
            raise SettleCommandFailed(
                "branch finalization requires a named branch; HEAD is detached"
            )
        if environment.branch == self.host_config.base_branch:
            raise SettleCommandFailed(
                f"refusing to finalize base branch {environment.branch!r} as a feature"
            )
        return environment.branch

    def _current_branch(self, cwd: Path) -> str:
        result = self._run_checked(["git", "branch", "--show-current"], cwd=cwd)
        return result.stdout.strip()

    def _confirm_branch_unmoved(self, environment: GitEnvironment, branch: str) -> None:
        """Re-read HEAD immediately before a destructive action.

        Detection ran earlier; a checkout in between would aim the delete at
        whatever branch HEAD landed on.
        """
        observed = self._current_branch(environment.worktree_root)
        if observed != branch:
            raise SettleCommandFailed(
                f"HEAD moved from {branch!r} to {observed or '(detached)'!r} "
                "since environment detection; refusing destructive finalization"
            )

    def _record_skipped_cleanup(
        self,
        *,
        feature_id: str,
        branch: str,
        environment: GitEnvironment,
        reason: str,
    ) -> None:
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_CLEANUP_SKIPPED,
                payload={
                    "feature_id": feature_id,
                    "branch": branch,
                    "worktree": str(environment.worktree_root),
                    "reason": reason,
                },
            )
        )

    def _roll_back_merge(
        self,
        *,
        feature_id: str,
        branch: str,
        merge_root: Path,
        base_sha: str,
        cause: SettleError,
    ) -> None:
        """Restore the base branch after a merge that must not stand.

        Records the attempt either way: an operator who sees the failure needs
        to know whether the base branch was actually restored.
        """
        rollback_error: SettleCommandFailed | None = None
        try:
            self._run_checked(
                ["git", "reset", "--hard", base_sha],
                cwd=merge_root,
            )
        except SettleCommandFailed as error:
            rollback_error = error
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_MERGE_ROLLED_BACK,
                payload={
                    "feature_id": feature_id,
                    "branch": branch,
                    "base_branch": self.host_config.base_branch,
                    "base_sha": base_sha,
                    "cause": str(cause),
                    "rollback_succeeded": rollback_error is None,
                },
            )
        )
        if rollback_error is not None:
            # Chain, so the failure that triggered the rollback survives.
            raise rollback_error from cause

    def _merge(
        self,
        *,
        feature_id: str,
        branch: str,
        environment: GitEnvironment,
    ) -> None:
        merge_root = (
            environment.repo_root
            if environment.is_worktree
            else environment.worktree_root
        )
        self._run_checked(
            ["git", "checkout", self.host_config.base_branch],
            cwd=merge_root,
        )
        self._run_checked(["git", "pull"], cwd=merge_root)
        base_sha = self._run_checked(
            ["git", "rev-parse", "HEAD"],
            cwd=merge_root,
        ).stdout.strip()
        try:
            # A conflicted merge leaves the base branch mid-merge, and a failing
            # post-merge test run leaves it merged. Both must be undone.
            self._run_checked(["git", "merge", branch], cwd=merge_root)
            self._run_tests(
                feature_id=feature_id,
                cwd=merge_root,
                phase="post_merge",
            )
        except SettleError as error:
            self._roll_back_merge(
                feature_id=feature_id,
                branch=branch,
                merge_root=merge_root,
                base_sha=base_sha,
                cause=error,
            )
            raise

        if not environment.is_worktree:
            self._run_checked(["git", "branch", "-d", branch], cwd=merge_root)
            return
        if not self._safe_worktree_cleanup(environment):
            self._record_skipped_cleanup(
                feature_id=feature_id,
                branch=branch,
                environment=environment,
                reason=(
                    "worktree provenance is not .worktrees/; the host owns this "
                    "workspace, so neither it nor the branch was removed"
                ),
            )
            return
        self._run_checked(
            ["git", "worktree", "remove", str(environment.worktree_root)],
            cwd=environment.repo_root,
        )
        self._run_checked(
            ["git", "branch", "-d", branch],
            cwd=environment.repo_root,
        )

    def _discard(
        self,
        *,
        branch: str,
        environment: GitEnvironment,
    ) -> None:
        if environment.is_worktree:
            if not self._safe_worktree_cleanup(environment):
                raise SettleUnsafeCleanupError(
                    "worktree provenance is not .worktrees/; refusing discard cleanup"
                )
            self._confirm_branch_unmoved(environment, branch)
            self._run_checked(
                [
                    "git",
                    "worktree",
                    "remove",
                    "--force",
                    str(environment.worktree_root),
                ],
                cwd=environment.repo_root,
            )
            self._run_checked(
                ["git", "branch", "-D", branch],
                cwd=environment.repo_root,
            )
            return
        self._confirm_branch_unmoved(environment, branch)
        self._run_checked(
            ["git", "checkout", self.host_config.base_branch],
            cwd=environment.worktree_root,
        )
        self._run_checked(
            ["git", "branch", "-D", branch],
            cwd=environment.worktree_root,
        )

    def _execute_disposition(
        self,
        *,
        feature_id: str,
        disposition: str,
        environment: GitEnvironment,
    ) -> None:
        if disposition == "kept":
            return

        branch = self._require_feature_branch(environment)
        if disposition == "pr_opened":
            self._run_checked(
                ["git", "push", "-u", "origin", branch],
                cwd=environment.worktree_root,
            )
            self._run_checked(
                [
                    "gh",
                    "pr",
                    "create",
                    "--fill",
                    "--base",
                    self.host_config.base_branch,
                    "--head",
                    branch,
                ],
                cwd=environment.worktree_root,
            )
            return

        if disposition == "merged":
            self._merge(
                feature_id=feature_id,
                branch=branch,
                environment=environment,
            )
            return

        if disposition == "discarded":
            self._discard(branch=branch, environment=environment)

    def run_settle(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        disposition: str,
    ) -> None:
        """Finalize one merge-ready feature using the selected disposition."""
        # TODO(plan8): wire supersession detection. When Settle identifies that
        # the merging feature supersedes a previously live scenario, this is
        # the site that must emit a SCENARIO_SUPERSESSION_REQUESTED event so
        # the DisciplineStage handler can call begin_supersession. The event
        # is intentionally NOT emitted today because supersession detection
        # itself is stubbed: firing unconditionally would corrupt the
        # mapping whenever a feature is settled. The placeholder below
        # documents the required payload shape and is a no-op.
        if disposition not in _VALID_DISPOSITIONS:
            raise ValueError(
                f"invalid disposition {disposition!r}; "
                f"expected one of {sorted(_VALID_DISPOSITIONS)}"
            )

        report_path = (
            context.project_dir / ".haileris" / "settle" / f"{feature_id}.md"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_ready_inspect(context, feature_id)

        queue = context.mapping.feature_cosmetic_queue
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_STARTED,
                payload={
                    "feature_id": feature_id,
                    "cosmetic_queue_size": len(queue),
                },
            )
        )
        cosmetic_path = report_path.with_name(f"{feature_id}-cosmetic.md")
        cosmetic_path.write_text(self._render_cosmetic_md(queue), encoding="utf-8")
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_COSMETIC_QUEUED,
                payload={"feature_id": feature_id, "queue_size": len(queue)},
            )
        )

        self._run_tests(
            feature_id=feature_id,
            cwd=context.project_dir,
            phase="pre_finalize",
        )
        environment = self._detect_environment(context.project_dir)
        self._execute_disposition(
            feature_id=feature_id,
            disposition=disposition,
            environment=environment,
        )

        # Write the report before flipping the mapping: a failed write must not
        # leave a persisted "settled" status with no record of what happened.
        report_path.write_text(
            self._render_report(
                feature_id=feature_id,
                disposition=disposition,
                queue_size=len(queue),
                environment=environment,
            ),
            encoding="utf-8",
        )
        context.mapping = context.mapping.model_copy(
            update={"feature_status": "settled"}
        )
        context.mapping.save(context.project_dir / "mapping.yaml")
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_FINALIZED,
                payload={
                    "feature_id": feature_id,
                    "disposition": disposition,
                    "branch": environment.branch,
                    "worktree": environment.is_worktree,
                },
            )
        )
        if disposition == "discarded":
            self.events_log.append_sync(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SETTLE_BRANCH_DISCARDED,
                    payload={"feature_id": feature_id},
                )
            )
        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_COMPLETED,
                payload={"feature_id": feature_id, "disposition": disposition},
            )
        )

    @staticmethod
    def _render_cosmetic_md(queue: list[dict]) -> str:
        if not queue:
            return "# Cosmetic Queue\n\n(empty)\n"
        lines = ["# Cosmetic Queue", ""]
        for index, item in enumerate(queue, 1):
            lines.append(
                f"{index}. **{item.get('sub_bid', '?')}** / "
                f"{item.get('scenario_name', '?')} "
                f"({item.get('proposed_by', '?')})\n"
                f"   - location: {item.get('location', '?')}\n"
                f"   - text: {item.get('text', '?')}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_report(
        *,
        feature_id: str,
        disposition: str,
        queue_size: int,
        environment: GitEnvironment,
    ) -> str:
        return (
            f"# Settle Feature {feature_id}\n\n"
            f"## Disposition\n\n{disposition}\n\n"
            f"## Cosmetic Queue ({queue_size} items)\n\n"
            f"See `{feature_id}-cosmetic.md` for the full list.\n\n"
            f"## Environment\n\n"
            f"- branch: {environment.branch or '(detached)'}\n"
            f"- worktree: {environment.is_worktree}\n\n"
            f"## Finalized at\n\n{datetime.now(UTC).isoformat()}\n"
        )
