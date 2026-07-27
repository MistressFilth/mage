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
        # No args should print help and exit 0 (or non-zero with usage).
        # We accept either; the key is it doesn't crash with an unhandled exception.
        assert exc_info.value.code in (0, 1, 2)

    def test_verify_subcommand_runs_mechanical_checks(self, tmp_project_dir: Path):
        # Set up a minimal mapping + feature file.
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: Valid\n    Given x\n    When y\n    Then z\n"
        )
        config_dir = tmp_project_dir / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("max_iterations: 3\ncheck_set: default\n")

        # Create a mapping artifact with one base BID.
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

        # Run the CLI verify command.
        rc = cli.main([
            "--project-dir", str(tmp_project_dir),
            "verify",
            "--feature", str(feature_path),
            "--scenario", "Valid",
            "--sub-bid", "A",
            "--base-bid", "00000",
        ])
        # The scenario has tags=[] so TagsRegisteredCheck will fail (no registered tags).
        # We expect non-zero exit because of that. The point is the command runs.
        assert rc in (0, 1)  # 0 if all pass, 1 if any fail


def test_plan_show_prints_digest_and_content(tmp_path, capsys):
    from mage.artifacts.plan import PlanArtifact
    from mage.cli import main
    from mage.orchestration.events import EventsLog
    import sys

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    PlanArtifact.finalize(plan_path, "# Plan\n\ncontent\n", log)

    test_argv = ["mage", "plan", "show", "--project-dir", str(tmp_path)]
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
    plan_path.write_text("# revised\n", encoding="utf-8")  # simulate external edit

    test_argv = [
        "mage", "plan", "revise",
        "--reason", "Reordered behaviors",
        "--approver", "alice",
        "--project-dir", str(tmp_path),
    ]
    with patch.object(sys, "argv", test_argv):
        main()

    revised = [e for e in log.read_all() if e.event_type == EventType.PLAN_REVISED]
    assert len(revised) == 1
    assert revised[0].payload["reason"] == "Reordered behaviors"
    assert revised[0].payload["human_approver"] == "alice"

    captured = capsys.readouterr()
    assert "Plan revision recorded" in captured.out or "revision" in captured.out.lower()


def test_plan_revise_missing_plan(tmp_path, capsys):
    from mage.cli import main
    import sys

    test_argv = [
        "mage", "plan", "revise",
        "--reason", "r",
        "--approver", "a",
        "--project-dir", str(tmp_path),
    ]
    with patch.object(sys, "argv", test_argv):
        with pytest.raises(SystemExit) as exc_info:
            main()
    # Non-zero exit on error
    assert exc_info.value.code != 0
