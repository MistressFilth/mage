"""Unit tests for `mage run --feature-id` plumbing (Plan 22).

Covers the `_resolve_feature_id` helper and the cmd_run integration that
threads the value into PipelineContext / FeatureRunner. Tag-only semantics:
no validation against saved state, no override of Ascertain-derived value.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

from mage.cli import _resolve_feature_id


def _save_pipeline_state(project: Path, feature_id: str) -> None:
    """Persist a pipeline context with ``feature_id`` for resume tests."""
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext

    state_dir = project / ".haileris" / "state"
    state_dir.mkdir(parents=True)
    saved = PipelineContext(
        project_dir=project,
        mapping=MappingArtifact(schema_version=2, project_id="e2e", base_bids=[]),
        events_log=EventsLog(project / "events.jsonl"),
        feature_id=feature_id,
    )
    (state_dir / "pipeline-state.yaml").write_text(
        yaml.safe_dump(saved.model_dump(mode="json"), sort_keys=False)
    )


class TestResolveFeatureId:
    def test_omitted_returns_empty_string(self):
        """Argparse default=None when flag is not passed → empty string."""

        args = argparse.Namespace(feature_id=None)
        assert _resolve_feature_id(args) == ""

    def test_non_empty_value_returns_stripped(self):
        """Explicit non-empty value passes through unchanged."""

        args = argparse.Namespace(feature_id="feat-X")
        assert _resolve_feature_id(args) == "feat-X"

    def test_empty_string_exits_with_code_2(self):
        """Explicit empty string → SystemExit(2) with stderr message."""

        args = argparse.Namespace(feature_id="")
        with pytest.raises(SystemExit) as exc_info:
            _resolve_feature_id(args)
        assert exc_info.value.code == 2

    def test_whitespace_only_exits_with_code_2(self):
        """Whitespace-only → SystemExit(2)."""

        args = argparse.Namespace(feature_id="   ")
        with pytest.raises(SystemExit) as exc_info:
            _resolve_feature_id(args)
        assert exc_info.value.code == 2

    def test_missing_attribute_returns_empty_string(self):
        """Attribute missing (e.g., from a different parser subcommand) → empty."""

        # no feature_id attribute
        args = argparse.Namespace()
        assert _resolve_feature_id(args) == ""


class TestCmdRunFeatureIdIntegration:
    """Tests that cmd_run threads --feature-id into PipelineContext / FeatureRunner."""

    def _run_cmd_run(self, args_list: list[str]):
        """Run `mage run` end-to-end via main() and return rc.

        Uses --dry-run to avoid real LLM calls. Captures SystemExit for
        expected error paths.
        """
        from mage.cli import main

        return main(args_list)

    def test_cmd_run_with_feature_id_sets_pipeline_context(self, tmp_path, monkeypatch):
        """--feature-id flag → PipelineContext.feature_id matches."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "mapping.yaml").write_text(
            "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
        )

        # Patch the graph.run to capture the context it received.
        from mage.orchestration import graph as graph_module

        captured: dict = {}

        async def fake_run(self, initial_context):
            captured["context"] = initial_context
            return initial_context

        monkeypatch.setattr(graph_module.PipelineGraph, "run", fake_run)

        rc = self._run_cmd_run(
            [
                "run",
                "--project-dir",
                str(project),
                "--dry-run",
                "--feature-id",
                "feat-X",
            ]
        )
        assert rc in (None, 0), f"mage run must succeed; got rc={rc}"
        assert captured["context"].feature_id == "feat-X"

    def test_cmd_run_omitted_feature_id_defaults_to_empty(self, tmp_path, monkeypatch):
        """No flag → PipelineContext.feature_id == ''."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "mapping.yaml").write_text(
            "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
        )

        from mage.orchestration import graph as graph_module

        captured: dict = {}

        async def fake_run(self, initial_context):
            captured["context"] = initial_context
            return initial_context

        monkeypatch.setattr(graph_module.PipelineGraph, "run", fake_run)

        rc = self._run_cmd_run(["run", "--project-dir", str(project), "--dry-run"])
        assert rc in (None, 0)
        assert captured["context"].feature_id == ""

    def test_cmd_run_rejects_empty_feature_id(self, tmp_path):
        """--feature-id '' → SystemExit(2)."""
        project = tmp_path / "proj"
        project.mkdir()

        with pytest.raises(SystemExit) as exc_info:
            self._run_cmd_run(
                [
                    "run",
                    "--project-dir",
                    str(project),
                    "--dry-run",
                    "--feature-id",
                    "",
                ]
            )
        assert exc_info.value.code == 2

    def test_cmd_run_overrides_saved_state_feature_id(self, tmp_path, monkeypatch):
        """Saved state has feature_id='feat-X'; CLI passes 'feat-Y' → final 'feat-Y' (rebadge)."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "mapping.yaml").write_text(
            "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
        )
        _save_pipeline_state(project, "feat-X")

        from mage.orchestration import graph as graph_module

        captured: dict = {}

        async def fake_run(self, initial_context):
            captured["context"] = initial_context
            return initial_context

        monkeypatch.setattr(graph_module.PipelineGraph, "run", fake_run)

        rc = self._run_cmd_run(
            [
                "run",
                "--project-dir",
                str(project),
                "--dry-run",
                "--feature-id",
                "feat-Y",
            ]
        )
        assert rc in (None, 0)
        assert captured["context"].feature_id == "feat-Y"

    def test_cmd_run_preserves_saved_feature_id_when_flag_omitted(
        self, tmp_path, monkeypatch
    ):
        """Saved state has feature_id='feat-X'; no flag → preserved as 'feat-X'."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "mapping.yaml").write_text(
            "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
        )
        _save_pipeline_state(project, "feat-X")

        from mage.orchestration import graph as graph_module

        captured: dict = {}

        async def fake_run(self, initial_context):
            captured["context"] = initial_context
            return initial_context

        monkeypatch.setattr(graph_module.PipelineGraph, "run", fake_run)

        rc = self._run_cmd_run(["run", "--project-dir", str(project), "--dry-run"])
        assert rc in (None, 0)
        assert captured["context"].feature_id == "feat-X"
