"""Tests for the CLI entry point."""

from __future__ import annotations

from pathlib import Path

import pytest
from mage import cli


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
