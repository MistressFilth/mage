"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.state_store import StateStore

# Variables git exports to its hooks. Any of them redirects a plain
# ``git`` invocation away from its ``cwd`` and at the exporting repository.
_INHERITED_GIT_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)

# XDG roots mage resolves, each also honoured under a ``MAGE_`` prefix.
_XDG_SPEC_VARS = (
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR",
)


@pytest.fixture(autouse=True)
def _isolate_ambient_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Detach every test from the invoking shell's git and XDG state.

    Two leaks, both of which make the suite pass or fail on machine state
    rather than on the code under test:

    * ``git`` exports ``GIT_DIR``, ``GIT_INDEX_FILE`` and friends to the hooks
      it runs. The ``make test`` pre-commit hook inherits them, so every
      ``subprocess.run(["git", ...], cwd=<temp repo>)`` retargets the *real*
      repository instead of the temporary one -- dozens of git-touching tests
      fail and stray fixture files get staged into the actual index.
    * A developer's real ``~/.config/mage/config.toml`` reaches the provider
      resolver, so tests expecting the no-LLM ``TestModel`` passthrough instead
      resolve a live provider and demand its API key.

    Clearing the git variables and pointing the XDG roots at ``tmp_path`` makes
    the suite behave identically from a shell, from inside a git hook, and on
    CI. Tests needing specific values still override them: a ``monkeypatch``
    call in the test body wins over this fixture.
    """
    for var in _INHERITED_GIT_ENV:
        monkeypatch.delenv(var, raising=False)

    xdg_root = tmp_path / "xdg"
    for var in _XDG_SPEC_VARS:
        monkeypatch.delenv(f"MAGE_{var}", raising=False)
        target = xdg_root / var.lower()
        target.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(var, str(target))


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
