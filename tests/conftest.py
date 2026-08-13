"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

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
    """A real ``StateStore`` backed by a real git repo (P32).

    Tests construct ``PipelineContext(state_store=state_store, ...)`` to
    match the production injection pattern. The store uses subprocess
    directly — a real git repo gives a real working state store that
    supports both read and write round-trips.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return StateStore(tmp_path, "feature-artifacts", identity=("T", "t@e"))


def init_git_repo(project_dir: Path) -> None:
    """Init a git repo at ``project_dir`` if not already initialized (P32).

    E2E fixtures that call ``mage run`` need a real git repo so the
    CLI's state store has somewhere to live. Idempotent: skips if a
    git dir already exists.
    """
    rev = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=project_dir,
        capture_output=True,
        check=False,
    )
    if rev.returncode == 0:
        return
    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


async def seed_mapping_on_state_store(
    project_dir: Path, mapping: MappingArtifact
) -> None:
    """Write ``mapping`` to the orphan branch at ``project_dir`` (P32).

    E2E fixtures that call production CLI commands need the mapping
    on the orphan branch; the working-tree file alone is no longer
    read by the production CLI.
    """
    init_git_repo(project_dir)
    state_store = StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))
    await mapping.save_to_state_store(state_store)


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
