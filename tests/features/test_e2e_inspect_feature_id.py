"""End-to-end tests for InspectLoop feature_id threading (Plan 12)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def _init_minimal_project(project: Path) -> None:
    (project / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
    )
    (project / "plan.md").write_text("# plan\n")
    (project / ".mage").mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@mage"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "e2e"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)


def test_e2e_inspect_journal_schema_supports_feature_id(tmp_path: Path):
    """Cosmetic queue schema includes feature_id field on every entry."""
    project = tmp_path / "proj"
    project.mkdir()
    _init_minimal_project(project)
    mapping = {
        "schema_version": 2,
        "project_id": "e2e",
        "base_bids": [],
        "feature_cosmetic_queue": [
            {
                "feature_id": "feat-1",
                "sub_bid": "00000-001",
                "text": "use constant",
                "location": {"file": "src/example.py", "line": 1},
                "proposed_by": "human",
            }
        ],
    }
    src = project / "src"
    src.mkdir()
    (src / "example.py").write_text("x = 1\n")
    (project / "mapping.yaml").write_text(yaml.safe_dump(mapping))
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=project, check=True)

    mapping = yaml.safe_load((project / "mapping.yaml").read_text())
    for entry in mapping.get("feature_cosmetic_queue", []):
        assert "feature_id" in entry
        assert entry["feature_id"] == "feat-1"


def test_e2e_cosmetic_apply_filters_by_feature_id(tmp_path: Path):
    """mage cosmetic apply feat-1 processes only feat-1 entries, not feat-2."""
    project = tmp_path / "proj"
    project.mkdir()
    _init_minimal_project(project)
    src = project / "src"
    src.mkdir()
    (src / "example.py").write_text("x = 1\ny = 2\n")
    mapping = {
        "schema_version": 2,
        "project_id": "e2e",
        "base_bids": [],
        "feature_cosmetic_queue": [
            {
                "feature_id": "feat-1",
                "sub_bid": "00000-001",
                "text": "use constant",
                "location": {"file": "src/example.py", "line": 1},
                "proposed_by": "human",
            },
            {
                "feature_id": "feat-2",
                "sub_bid": "00000-002",
                "text": "rename var",
                "location": {"file": "src/example.py", "line": 2},
                "proposed_by": "human",
            },
        ],
    }
    (project / "mapping.yaml").write_text(yaml.safe_dump(mapping))
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=project, check=True)

    subprocess.run(
        [
            "mage",
            "cosmetic",
            "apply",
            "feat-1",
            "--project-dir",
            str(project),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    log = subprocess.run(
        ["cat", str(project / "events.jsonl")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "00000-001" in log.stdout, (
        "feat-1's sub_bid (00000-001) should appear in events.jsonl"
    )
