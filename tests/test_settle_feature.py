"""Tests for SettleFeatureStage readiness and branch finalization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from mage.artifacts.inspect import (
    CosmeticItem,
    InspectArtifact,
    InspectArtifactContent,
    InspectArtifactDigestMismatchError,
)
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.settle_feature import (
    SettleCommandFailed,
    SettleFeatureStage,
    SettleNotReadyError,
    SettleTestsFailed,
    SettleUnsafeCleanupError,
)
from mage.verification.host_overrides import HostConfig


TEST_COMMAND = ["uv", "run", "pytest", "-v"]


def finalize_inspect(
    project: Path,
    log: EventsLog,
    *,
    path_feature_id: str = "feat-1",
    content_feature_id: str = "feat-1",
    iteration: int = 1,
    ready: bool = True,
) -> Path:
    path = (
        project
        / ".haileris"
        / "inspect"
        / path_feature_id
        / f"{iteration}.yaml"
    )
    content = InspectArtifactContent(
        feature_id=content_feature_id,
        inspected_at=datetime.now(UTC),
        iteration=iteration,
        eof_max_iterations=3,
        ready_to_merge=ready,
    )
    InspectArtifact.finalize(path, content, log)
    return path


def make_context(project: Path, *, ready: bool = True) -> PipelineContext:
    project.mkdir(parents=True, exist_ok=True)
    log = EventsLog(project / "events.jsonl")
    finalize_inspect(project, log, ready=ready)
    return PipelineContext(
        project_dir=project,
        mapping=MappingArtifact(project_id="feat-1"),
        events_log=log,
        plan_path=project / "plan.md",
        iteration=0,
    )


class RecordingRunner:
    def __init__(
        self,
        project: Path,
        *,
        worktree: bool = False,
        branch: str = "feature/inspect-settle",
        test_returncodes: list[int] | None = None,
        fail_command: list[str] | None = None,
    ) -> None:
        self.project = project
        self.worktree = worktree
        self.branch = branch
        self.test_returncodes = list(test_returncodes or [])
        self.fail_command = fail_command
        self.calls: list[tuple[list[str], Path]] = []
        self.repo_root = (
            next(parent for parent in project.parents if parent.name == "repo")
            if worktree
            else project
        )

    def __call__(self, command: list[str], *, cwd: Path) -> CompletedProcess[str]:
        command = list(command)
        cwd = Path(cwd)
        self.calls.append((command, cwd))
        if self.fail_command == command:
            return CompletedProcess(command, 1, stdout="", stderr="command failed")
        if command == TEST_COMMAND:
            returncode = self.test_returncodes.pop(0) if self.test_returncodes else 0
            return CompletedProcess(
                command,
                returncode,
                stdout="tests passed" if returncode == 0 else "",
                stderr="" if returncode == 0 else "tests failed",
            )
        outputs = {
            ("git", "rev-parse", "--git-dir"): (
                str(self.repo_root / ".git" / "worktrees" / "feature")
                if self.worktree
                else str(self.project / ".git")
            ),
            ("git", "rev-parse", "--git-common-dir"): str(
                self.repo_root / ".git"
            ),
            ("git", "rev-parse", "--show-toplevel"): str(self.project),
            ("git", "branch", "--show-current"): self.branch,
        }
        return CompletedProcess(
            command,
            0,
            stdout=outputs.get(tuple(command), "") + "\n",
            stderr="",
        )


class TestSettleReadiness:
    def test_requires_an_inspect_artifact(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        context = PipelineContext(
            project_dir=project,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
        )
        runner = RecordingRunner(project)

        with pytest.raises(SettleNotReadyError, match="No InspectArtifact"):
            SettleFeatureStage(log, command_runner=runner).run_settle(
                context,
                feature_id="feat-1",
                disposition="kept",
            )

        assert runner.calls == []

    def test_requires_latest_artifact_to_be_ready(self, tmp_path):
        context = make_context(tmp_path / "project", ready=False)
        runner = RecordingRunner(context.project_dir)

        with pytest.raises(SettleNotReadyError, match="not ready"):
            SettleFeatureStage(
                context.events_log,
                command_runner=runner,
            ).run_settle(context, feature_id="feat-1", disposition="kept")

        assert runner.calls == []

    def test_requires_artifact_feature_id_to_match(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        finalize_inspect(
            project,
            log,
            path_feature_id="feat-1",
            content_feature_id="other-feature",
        )
        context = PipelineContext(
            project_dir=project,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
        )

        with pytest.raises(SettleNotReadyError, match="feature_id"):
            SettleFeatureStage(
                log,
                command_runner=RecordingRunner(project),
            ).run_settle(context, feature_id="feat-1", disposition="kept")

    def test_digest_mismatch_aborts_settle(self, tmp_path):
        context = make_context(tmp_path / "project")
        inspect_path = (
            context.project_dir / ".haileris" / "inspect" / "feat-1" / "1.yaml"
        )
        inspect_path.write_text(inspect_path.read_text() + "# tampered\n")

        with pytest.raises(InspectArtifactDigestMismatchError):
            SettleFeatureStage(
                context.events_log,
                command_runner=RecordingRunner(context.project_dir),
            ).run_settle(context, feature_id="feat-1", disposition="kept")

    def test_latest_iteration_is_selected_numerically(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        finalize_inspect(project, log, iteration=9, ready=False)
        finalize_inspect(project, log, iteration=10, ready=True)
        context = PipelineContext(
            project_dir=project,
            mapping=MappingArtifact(project_id="feat-1"),
            events_log=log,
        )
        runner = RecordingRunner(project)

        SettleFeatureStage(log, command_runner=runner).run_settle(
            context,
            feature_id="feat-1",
            disposition="kept",
        )

        assert context.mapping.feature_status == "settled"


class TestSettleFinalization:
    def test_failed_tests_emit_halt_without_finalizing(self, tmp_path):
        context = make_context(tmp_path / "project")
        original_mapping = context.mapping
        runner = RecordingRunner(context.project_dir, test_returncodes=[1])
        stage = SettleFeatureStage(context.events_log, command_runner=runner)

        with pytest.raises(SettleTestsFailed):
            stage.run_settle(
                context,
                feature_id="feat-1",
                disposition="kept",
            )

        event_types = [event.event_type.value for event in context.events_log.read_all()]
        assert event_types.count("settle_tests_failed") == 1
        assert "settle_feature_finalized" not in event_types
        assert context.mapping == original_mapping
        assert not (context.project_dir / "mapping.yaml").exists()

    def test_keep_writes_reports_and_atomically_settles_mapping(self, tmp_path):
        context = make_context(tmp_path / "project")
        context.mapping = context.mapping.append_cosmetic(
            CosmeticItem(
                sub_bid="000000",
                scenario_name="happy",
                location="Given step",
                text="Rephrase for clarity",
                proposed_by="scenario_clarity",
            )
        )
        runner = RecordingRunner(context.project_dir)
        stage = SettleFeatureStage(context.events_log, command_runner=runner)

        stage.run_settle(context, feature_id="feat-1", disposition="kept")

        assert runner.calls[0] == (TEST_COMMAND, context.project_dir)
        assert context.mapping.feature_status == "settled"
        assert MappingArtifact.load(context.project_dir / "mapping.yaml") == context.mapping
        report = context.project_dir / ".haileris" / "settle" / "feat-1.md"
        cosmetic = (
            context.project_dir / ".haileris" / "settle" / "feat-1-cosmetic.md"
        )
        assert report.exists()
        assert cosmetic.exists()
        assert "kept" in report.read_text()
        event_types = [event.event_type.value for event in context.events_log.read_all()]
        assert event_types[-2:] == [
            "settle_feature_finalized",
            "settle_feature_completed",
        ]

    def test_push_and_pr_executes_both_commands(self, tmp_path):
        context = make_context(tmp_path / "project")
        runner = RecordingRunner(context.project_dir)

        SettleFeatureStage(
            context.events_log,
            command_runner=runner,
        ).run_settle(context, feature_id="feat-1", disposition="pr_opened")

        assert (
            ["git", "push", "-u", "origin", "feature/inspect-settle"],
            context.project_dir,
        ) in runner.calls
        assert (
            [
                "gh",
                "pr",
                "create",
                "--fill",
                "--base",
                "main",
                "--head",
                "feature/inspect-settle",
            ],
            context.project_dir,
        ) in runner.calls

    def test_failed_branch_action_does_not_emit_finalized(self, tmp_path):
        context = make_context(tmp_path / "project")
        failing = ["git", "push", "-u", "origin", "feature/inspect-settle"]
        runner = RecordingRunner(context.project_dir, fail_command=failing)

        with pytest.raises(SettleCommandFailed, match="git push"):
            SettleFeatureStage(
                context.events_log,
                command_runner=runner,
            ).run_settle(context, feature_id="feat-1", disposition="pr_opened")

        assert not any(
            event.event_type.value == "settle_feature_finalized"
            for event in context.events_log.read_all()
        )
        assert context.mapping.feature_status != "settled"

    def test_merge_retests_deletes_branch_and_cleans_safe_worktree(self, tmp_path):
        project = tmp_path / "repo" / ".worktrees" / "feature"
        context = make_context(project)
        runner = RecordingRunner(project, worktree=True, test_returncodes=[0, 0])

        SettleFeatureStage(
            context.events_log,
            command_runner=runner,
        ).run_settle(context, feature_id="feat-1", disposition="merged")

        repo_root = tmp_path / "repo"
        assert runner.calls.count((TEST_COMMAND, project)) == 1
        assert (TEST_COMMAND, repo_root) in runner.calls
        assert (["git", "checkout", "main"], repo_root) in runner.calls
        assert (["git", "pull"], repo_root) in runner.calls
        assert (
            ["git", "merge", "feature/inspect-settle"],
            repo_root,
        ) in runner.calls
        assert (
            ["git", "worktree", "remove", str(project)],
            repo_root,
        ) in runner.calls
        assert (
            ["git", "branch", "-d", "feature/inspect-settle"],
            repo_root,
        ) in runner.calls

    def test_discard_force_deletes_branch_and_cleans_safe_worktree(self, tmp_path):
        project = tmp_path / "repo" / ".worktrees" / "feature"
        context = make_context(project)
        runner = RecordingRunner(project, worktree=True)

        SettleFeatureStage(
            context.events_log,
            command_runner=runner,
        ).run_settle(context, feature_id="feat-1", disposition="discarded")

        repo_root = tmp_path / "repo"
        assert (
            ["git", "worktree", "remove", "--force", str(project)],
            repo_root,
        ) in runner.calls
        assert (
            ["git", "branch", "-D", "feature/inspect-settle"],
            repo_root,
        ) in runner.calls
        assert any(
            event.event_type.value == "settle_branch_discarded"
            for event in context.events_log.read_all()
        )

    def test_discard_refuses_harness_owned_worktree_cleanup(self, tmp_path):
        project = tmp_path / "repo" / ".claude" / "worktrees" / "feature"
        context = make_context(project)
        runner = RecordingRunner(project, worktree=True)

        with pytest.raises(SettleUnsafeCleanupError, match="provenance"):
            SettleFeatureStage(
                context.events_log,
                command_runner=runner,
            ).run_settle(context, feature_id="feat-1", disposition="discarded")

        assert not any(
            command[:3] == ["git", "worktree", "remove"]
            for command, _cwd in runner.calls
        )

    def test_run_delegates_to_configured_settle(self, tmp_path):
        context = make_context(tmp_path / "project")
        runner = RecordingRunner(context.project_dir)
        stage = SettleFeatureStage(
            context.events_log,
            command_runner=runner,
            feature_id="feat-1",
            disposition="kept",
        )

        result = stage.run(context)

        assert result is context
        assert context.mapping.feature_status == "settled"
