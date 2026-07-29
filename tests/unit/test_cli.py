"""Tests for the CLI entry point."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from mage import cli
from unittest.mock import patch


class TestCli:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--help"])
        assert exc_info.value.code == 0

    def test_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main([])
        assert exc_info.value.code in (0, 1, 2)

    def test_verify_subcommand_runs_mechanical_checks(self, tmp_project_dir: Path):
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: Valid\n    Given x\n    When y\n    Then z\n"
        )
        config_dir = tmp_project_dir / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("max_iterations: 3\ncheck_set: default\n")

        from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact
        mapping = MappingArtifact(
            schema_version=1,
            project_id="cli-test",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b",
                    behavior_description="d",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        mapping.save(tmp_project_dir / "mapping.yaml")

        rc = cli.main([
            "--project-dir", str(tmp_project_dir),
            "verify",
            "--feature", str(feature_path),
            "--scenario", "Valid",
            "--sub-bid", "A",
            "--base-bid", "00000",
        ])
        assert rc in (0, 1)


def test_plan_show_prints_digest_and_content(tmp_path, capsys):
    from mage.artifacts.plan import PlanArtifact
    from mage.cli import main
    from mage.orchestration.events import EventsLog
    import sys

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# Plan\n\ncontent\n", log)

    test_argv = ["mage", "--project-dir", str(tmp_path), "plan", "show"]
    with patch.object(sys, "argv", test_argv):
        main()

    captured = capsys.readouterr()
    assert "Plan:" in captured.out
    assert str(plan_path) in captured.out
    assert "Digest:" in captured.out
    assert "# Plan" in captured.out


def test_plan_revise_records_event(tmp_path, capsys):
    from mage.artifacts.plan import PlanArtifact
    from mage.cli import main
    from mage.orchestration.events import EventsLog, EventType
    import sys

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# original\n", log)
    plan_path.write_text("# revised\n", encoding="utf-8")

    test_argv = [
        "mage", "--project-dir", str(tmp_path),
        "plan", "revise",
        "--reason", "Reordered behaviors",
        "--approver", "alice",
    ]
    with patch.object(sys, "argv", test_argv):
        main()

    revised = [e for e in log.read_all() if e.event_type == EventType.PLAN_REVISED]
    assert len(revised) == 1
    assert revised[0].payload["reason"] == "Reordered behaviors"
    assert revised[0].payload["human_approver"] == "alice"

    captured = capsys.readouterr()
    assert "Plan revision recorded" in captured.out or "revision" in captured.out.lower()


def test_plan_revise_warns_on_unchanged_digest(tmp_path, capsys):
    from mage.artifacts.plan import PlanArtifact
    from mage.cli import main
    from mage.orchestration.events import EventsLog
    import sys

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# same\n", log)

    test_argv = [
        "mage", "--project-dir", str(tmp_path),
        "plan", "revise",
        "--reason", "r",
        "--approver", "a",
    ]
    with patch.object(sys, "argv", test_argv):
        main()

    captured = capsys.readouterr()
    assert "Plan digest unchanged; recording anyway" in captured.err


def test_plan_revise_missing_plan(tmp_path, capsys):
    from mage.cli import main
    import sys

    test_argv = [
        "mage", "--project-dir", str(tmp_path),
        "plan", "revise",
        "--reason", "r",
        "--approver", "a",
    ]
    with patch.object(sys, "argv", test_argv):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code != 0


def test_mage_run_raises_not_implemented(tmp_path, capsys):
    from mage.cli import main
    import sys

    test_argv = ["mage", "--project-dir", str(tmp_path), "run"]
    with patch.object(sys, "argv", test_argv):
        with pytest.raises(NotImplementedError, match="deferred to Plan 6"):
            main()


def test_review_show_prints_latest_aggregate(tmp_path, capsys):
    from mage.artifacts.verdict import (
        VerdictArtifact, ReviewerAggregate, DimensionSummary,
    )
    from mage.cli import main
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    import sys

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")

    agg = ReviewerAggregate(
        draft_hash="x", aggregated_at=datetime.now(UTC), iteration=1,
        per_dimension={
            "spec_compliance": DimensionSummary(
                outcome="pass", reviewer_verdict_ref="r.yaml", findings_count=0,
            ),
        },
        decision="approved", reasoning="all passed",
    )
    path = project_dir / "agg.yaml"
    VerdictArtifact.finalize(path, agg, log)

    test_argv = ["mage", "--project-dir", str(project_dir), "review", "show"]
    with patch.object(sys, "argv", test_argv):
        rc = main()
    assert rc == 0

    captured = capsys.readouterr()
    assert "approved" in captured.out


def test_review_resume_requires_halt_event(tmp_path, capsys):
    from mage.cli import main

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    # No halt event written
    with pytest.raises(SystemExit) as exc_info:
        main(["review", "resume", "--project-dir", str(project_dir)])
    # Should exit non-zero (no halt to resume)
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "halt" in captured.err.lower()


def test_review_resume_with_halt_event(tmp_path, capsys):
    from mage.cli import main
    from mage.orchestration.events import EventsLog, Event, EventType
    from datetime import datetime, UTC

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    log.append(Event(
        timestamp=datetime.now(UTC),
        event_type=EventType.REVIEW_HALT_PERSISTED,
        payload={"base_bid": "00000", "iteration": 3},
    ))

    rc = main(["review", "resume", "--project-dir", str(project_dir)])
    # Resume is currently a placeholder (Plan 6 wires the pipeline)
    assert rc == 0
    captured = capsys.readouterr()
    assert "ready" in captured.out.lower() or "resume" in captured.out.lower()


class TestInspectShow:
    def test_inspect_show_renders_artifact(self, tmp_path, capsys):
        from datetime import UTC, datetime

        from mage.orchestration.events import EventsLog
        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.cli import main

        # Build a minimal project with an InspectArtifact
        project = tmp_path / "proj"
        project.mkdir()
        inspect_dir = project / ".haileris" / "inspect" / "feat-1"
        inspect_dir.mkdir(parents=True)
        log = EventsLog(project / "events.jsonl")
        artifact = InspectArtifactContent(
            feature_id="feat-1",
            inspected_at=datetime.now(UTC),
            iteration=1,
            eof_max_iterations=3,
            scenarios=[],
            per_reviewer=[],
            critical=[],
            important=[],
            minor=[],
            cross_scenario=[],
            ready_to_merge=True,
            ledger_markdown="| step | result |\n|---|---|\n| mechanical | pass |",
        )
        InspectArtifact.finalize(inspect_dir / "1.yaml", artifact, log)

        rc = main(["inspect", "show", "feat-1", "--project-dir", str(project)])
        out = capsys.readouterr().out
        assert "feat-1" in out
        assert "ready_to_merge" in out or "Ready" in out
        assert rc == 0


class TestSettleRun:
    @staticmethod
    def _install_runner(monkeypatch, project, *, test_returncode=0):
        from subprocess import CompletedProcess

        def runner(command, *, cwd):
            outputs = {
                ("git", "rev-parse", "--git-dir"): str(project / ".git"),
                ("git", "rev-parse", "--git-common-dir"): str(project / ".git"),
                ("git", "rev-parse", "--show-toplevel"): str(project),
                ("git", "branch", "--show-current"): "feature/settle",
            }
            returncode = (
                test_returncode
                if command == ["uv", "run", "pytest", "-v"]
                else 0
            )
            return CompletedProcess(
                command,
                returncode,
                stdout=outputs.get(tuple(command), "") + "\n",
                stderr="tests failed" if returncode else "",
            )

        monkeypatch.setattr(
            "mage.orchestration.settle_feature._default_command_runner",
            runner,
        )

    def test_settle_run_non_interactive(self, tmp_path, capsys, monkeypatch):
        from mage.orchestration.events import EventsLog
        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.cli import main

        project = tmp_path / "proj"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        self._install_runner(monkeypatch, project)

        # Build a ready-to-merge InspectArtifact
        inspect_dir = project / ".haileris" / "inspect" / "feat-1"
        inspect_dir.mkdir(parents=True)
        artifact = InspectArtifactContent(
            feature_id="feat-1",
            inspected_at=datetime.now(UTC),
            iteration=1,
            eof_max_iterations=3,
            scenarios=[],
            per_reviewer=[],
            critical=[],
            important=[],
            minor=[],
            cross_scenario=[],
            ready_to_merge=True,
            ledger_markdown="",
        )
        InspectArtifact.finalize(inspect_dir / "1.yaml", artifact, log)

        rc = main(["settle", "run", "feat-1", "--disposition", "kept", "--project-dir", str(project)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "settle" in out.lower() or "feat-1" in out

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "settle_feature_finalized" in types
        disposal_events = [e for e in events if e.event_type.value == "settle_feature_finalized"]
        assert disposal_events[0].payload["disposition"] == "kept"

    def test_settle_run_returns_nonzero_when_tests_fail(
        self,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.cli import main
        from mage.orchestration.events import EventsLog

        project = tmp_path / "proj"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        self._install_runner(monkeypatch, project, test_returncode=1)
        InspectArtifact.finalize(
            project / ".haileris" / "inspect" / "feat-1" / "1.yaml",
            InspectArtifactContent(
                feature_id="feat-1",
                inspected_at=datetime.now(UTC),
                iteration=1,
                eof_max_iterations=3,
                ready_to_merge=True,
            ),
            log,
        )

        rc = main(
            [
                "settle",
                "run",
                "feat-1",
                "--disposition",
                "kept",
                "--project-dir",
                str(project),
            ]
        )

        assert rc == 1
        assert "tests failed" in capsys.readouterr().err.lower()
        assert not any(
            event.event_type.value == "settle_feature_finalized"
            for event in log.read_all()
        )

    def test_settle_run_reports_value_errors_without_traceback(
        self,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        from mage.cli import main
        from mage.orchestration.settle_feature import SettleFeatureStage

        project = tmp_path / "proj"
        project.mkdir()

        def explode(self, context, *, feature_id, disposition):
            raise ValueError("mapping artifact is missing base_bids")

        monkeypatch.setattr(SettleFeatureStage, "run_settle", explode)

        rc = main(
            [
                "settle",
                "run",
                "feat-1",
                "--disposition",
                "kept",
                "--project-dir",
                str(project),
            ]
        )

        assert rc == 1
        assert "base_bids" in capsys.readouterr().err
