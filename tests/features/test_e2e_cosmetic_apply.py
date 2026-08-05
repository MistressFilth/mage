"""End-to-end tests for `mage cosmetic apply`.

Plan 10, Task 5. Three black-box E2E tests against the real CLI:

1. ``test_e2e_cosmetic_apply_writes_files_and_commits`` — happy path:
   one queue item; the file is edited and a git commit is created with
   the message ``cosmetic(<sub_bid>): <rationale>``.
2. ``test_e2e_cosmetic_apply_idempotent`` — running apply twice must
   not create a second git commit (idempotency state is consulted).
3. ``test_e2e_cosmetic_apply_failed_event_on_missing_file`` —
   target file does not exist; ``cosmetic_apply_failed`` event is
   emitted; ``rc == 0`` (partial success).

All three run against ``main([...])`` — no ``cli.main`` monkeypatching.
The LLM is the real Pydantic-AI ``TestModel`` selected by ``--model test``.
Git is the real ``subprocess.run``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _write_minimal_project(project: Path) -> None:
    """Write a minimal valid mapping.yaml and initialize a git repo.

    Creates ``mapping.yaml`` (``schema_version: 2``, ``project_id: e2e``,
    empty ``base_bids``), the ``.mage/`` directory, and initializes
    a git repo with an initial commit so ``git commit -am`` later in
    ``cmd_cosmetic_apply`` has something to amend onto.
    """
    (project / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
    )
    (project / ".mage").mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@mage"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "e2e"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)


def _seed_mapping(project: Path, feature_id: str, items: list[dict]) -> None:
    """Write a mapping.yaml containing the given ``feature_cosmetic_queue``.

    Each entry must satisfy the Task 2 validator: non-empty ``feature_id``
    plus ``sub_bid``, ``text``, ``location: {file, line}``, ``proposed_by``.
    """
    import yaml

    mapping = {
        "schema_version": 2,
        "project_id": "e2e",
        "base_bids": [],
        "feature_cosmetic_queue": items,
    }
    (project / "mapping.yaml").write_text(yaml.safe_dump(mapping))


def test_e2e_cosmetic_apply_writes_files_and_commits(tmp_path: Path) -> None:
    """A real cosmetic apply writes a target file and creates a git commit."""
    project = tmp_path / "proj"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    target = src / "module.py"
    target.write_text("def f():\n    return 42\n")
    _write_minimal_project(project)
    _seed_mapping(
        project,
        "feat-1",
        [
            {
                "feature_id": "feat-1",
                "sub_bid": "00000-001",
                "text": "extract constant",
                "location": {"file": "src/module.py", "line": 2},
                "proposed_by": "e2e",
            }
        ],
    )

    from mage.cli import main

    rc = main(
        [
            "cosmetic",
            "apply",
            "feat-1",
            "--project-dir",
            str(project),
            "--model",
            "test",
        ]
    )
    assert rc == 0
    # The test-mode passthrough writes raw["text"] + "\n" as the
    # replacement. We assert the file content actually contains that
    # marker — not merely "different from the original".
    edited = target.read_text()
    assert "extract constant" in edited, (
        f"target file must contain the cosmetic text via test-mode passthrough; got: {edited!r}"
    )
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "cosmetic(00000-001)" in log.stdout


def test_e2e_cosmetic_apply_idempotent(tmp_path: Path) -> None:
    """Re-running apply with same content emits SKIPPED, no second commit."""
    project = tmp_path / "proj"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    target = src / "module.py"
    target.write_text("def f():\n    return 42\n")
    _write_minimal_project(project)
    _seed_mapping(
        project,
        "feat-1",
        [
            {
                "feature_id": "feat-1",
                "sub_bid": "00000-001",
                "text": "extract constant",
                "location": {"file": "src/module.py", "line": 2},
                "proposed_by": "e2e",
            }
        ],
    )

    from mage.cli import main

    main(
        [
            "cosmetic",
            "apply",
            "feat-1",
            "--project-dir",
            str(project),
            "--model",
            "test",
        ]
    )
    first_count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    main(
        [
            "cosmetic",
            "apply",
            "feat-1",
            "--project-dir",
            str(project),
            "--model",
            "test",
        ]
    )
    second_count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert first_count == second_count, "Second apply must not create a new git commit"


def test_e2e_cosmetic_apply_failed_event_on_missing_file(tmp_path: Path) -> None:
    """Missing target file → ``cosmetic_apply_failed`` event; rc == 0."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_minimal_project(project)
    _seed_mapping(
        project,
        "feat-1",
        [
            {
                "feature_id": "feat-1",
                "sub_bid": "00000-001",
                "text": "edit a missing file",
                "location": {"file": "src/does_not_exist.py", "line": 1},
                "proposed_by": "e2e",
            }
        ],
    )

    from mage.cli import main

    rc = main(
        [
            "cosmetic",
            "apply",
            "feat-1",
            "--project-dir",
            str(project),
            "--model",
            "test",
        ]
    )
    assert rc == 0  # partial success
    events_log = project / "events.jsonl"
    assert events_log.exists()
    assert "cosmetic_apply_failed" in events_log.read_text()
