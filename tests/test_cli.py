"""Tests for the CLI entry point."""

from __future__ import annotations

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
