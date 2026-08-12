"""Pytest configuration and shared fixtures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.state_store import StateStore


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Provide an isolated project directory for tests."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def state_store(tmp_path: Path) -> StateStore:
    """A real ``StateStore`` with a ``MagicMock`` command runner (P32).

    Tests construct ``PipelineContext(state_store=state_store, ...)`` to
    match the production injection pattern. The runner is a mock so tests
    never shell out.
    """
    return StateStore(
        tmp_path,
        "feature-artifacts",
        identity=("T", "t@e"),
        command_runner=MagicMock(),
    )


@pytest.fixture
def cosmetic_queue() -> Callable[..., MappingArtifact]:
    """Return a builder for `MappingArtifact` populated with cosmetic findings.

    The returned callable builds and returns a `MappingArtifact`. Tests that
    need a serialized `mapping.yaml` on disk can write it themselves; the
    builder keeps the in-memory construction central.

    Usage::

        def test_x(cosmetic_queue):
            artifact = cosmetic_queue(
                feature_id="feat",
                findings=[{
                    "sub_bid": "01JF...", "scenario_name": "...",
                    "location": "src/x.py", "text": "...",
                    "proposed_by": "increment_quality",
                }],
            )
    """

    def _build(*, feature_id: str, findings: list[dict]) -> MappingArtifact:
        return MappingArtifact(
            project_id="demo",
            cosmetic_findings=[
                {**finding, "feature_id": feature_id} for finding in findings
            ],
        )

    return _build
