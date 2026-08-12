"""End-to-end tests for the cosmetic watcher daemon."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest

from mage.artifacts.cosmetic_state import load_state


def _write_minimal_project(project: Path) -> None:
    (project / ".mage").mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@mage"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "e2e"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)


def _seed_mapping(project: Path, feature_id: str, sub_bid: str) -> None:
    """Seed the orphan-branch mapping the watcher reads from (P32 task 10 fix).

    P32: ``mapping.yaml`` lives on ``refs/mage/feature-artifacts``, not
    the working tree. The watcher's catch-up call uses
    ``MappingArtifact.load_from_state_store`` so a working-tree write
    is invisible to it. Seed via ``save_to_state_store`` so the test
    triggers the real path.
    """
    from mage.artifacts.mapping import MappingArtifact
    from mage.state_store import state_store_for

    mapping = MappingArtifact(
        project_id="e2e",
        cosmetic_findings=[
            {
                "feature_id": feature_id,
                "sub_bid": sub_bid,
                "scenario_name": "scenario",
                "text": "extract constant",
                "location": "src/module.py",
                "proposed_by": "e2e",
            }
        ],
    )
    state_store = state_store_for(project, mage_toml=None)
    asyncio.run(mapping.save_to_state_store(state_store))


def _spawn_watcher(project: Path, *, poll_ms: int = 50) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "mage",
            "cosmetic",
            "watch",
            "--project-dir",
            str(project),
            "--poll-interval-ms",
            str(poll_ms),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_e2e_cosmetic_watcher_applies_new_queue_entries(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    (src / "module.py").write_text("def f():\n    return 42\n")
    _write_minimal_project(project)
    _seed_mapping(project, "feat-1", "00000-001")

    watcher = _spawn_watcher(project, poll_ms=50)
    try:
        subprocess.run(
            ["mage", "mapping", "save", "--project-dir", str(project)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        for _ in range(40):
            state = load_state(project)
            if state.applied:
                break
            time.sleep(0.1)
        else:
            pytest.fail("watcher did not apply within 4s")
    finally:
        watcher.terminate()
        watcher.wait(timeout=5)

    assert (src / "module.py").read_text() != "def f():\n    return 42\n"
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "cosmetic(00000-001)" in log.stdout


def test_e2e_cosmetic_watcher_idempotent_across_saves(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    (src / "module.py").write_text("def f():\n    return 42\n")
    _write_minimal_project(project)
    _seed_mapping(project, "feat-1", "00000-001")

    subprocess.run(
        ["mage", "mapping", "save", "--project-dir", str(project)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    watcher = _spawn_watcher(project, poll_ms=50)
    try:
        for _ in range(40):
            state = load_state(project)
            if state.applied:
                break
            time.sleep(0.1)
        subprocess.run(
            ["mage", "mapping", "save", "--project-dir", str(project)],
            capture_output=True,
            timeout=10,
            check=False,
        )
        time.sleep(0.5)
    finally:
        watcher.terminate()
        watcher.wait(timeout=5)

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    cosmetic_commits = [
        line for line in log.stdout.splitlines() if "cosmetic(00000-001)" in line
    ]
    assert len(cosmetic_commits) == 1, (
        f"watcher should apply only once; got {len(cosmetic_commits)} commits"
    )
