"""End-to-end tests for the cosmetic watcher daemon."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from mage.artifacts.cosmetic_state import load_state


def _write_minimal_project(project: Path) -> None:
    (project / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
    )
    (project / ".haileris").mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@mage"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "e2e"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)


def _seed_mapping(project: Path, feature_id: str, sub_bid: str) -> None:
    import yaml

    mapping = {
        "schema_version": 2,
        "project_id": "e2e",
        "base_bids": [],
        "feature_cosmetic_queue": [
            {
                "feature_id": feature_id,
                "sub_bid": sub_bid,
                "text": "extract constant",
                "location": {"file": "src/module.py", "line": 2},
                "proposed_by": "e2e",
            }
        ],
    }
    (project / "mapping.yaml").write_text(yaml.safe_dump(mapping))


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
        result = subprocess.run(
            ["mage", "mapping", "save", "--project-dir", str(project)],
            capture_output=True,
            text=True,
            timeout=10,
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
    )
    cosmetic_commits = [
        line for line in log.stdout.splitlines() if "cosmetic(00000-001)" in line
    ]
    assert len(cosmetic_commits) == 1, (
        f"watcher should apply only once; got {len(cosmetic_commits)} commits"
    )
