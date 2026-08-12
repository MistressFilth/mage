"""Inspect artifact + verdict + settle report I/O uses StateStore (P32 task 12).

The pre-migration paths were ``<project_dir>/.mage/inspect/...``,
``<project_dir>/.mage/verdicts/...``, and ``<project_dir>/.mage/settle/...``.
After P32, those artifacts live on the orphan branch at ``inspect/...``,
``verdicts/...``, and ``settle/...`` (relative paths), written via the
:class:`mage.state_store.StateStore`. This module pins the path
conventions:

- ``inspect/<feature_id>/<iteration>.yaml`` round-trips through
  ``StateStore.write``/``read``.
- ``verdicts/<draft_hash>/<dimension>.yaml`` round-trips the same way.
- ``settle/<feature_id>.md`` round-trips the same way.

The full ``InspectArtifact.finalize_to_state_store`` /
``InspectArtifact.load_from_state_store`` /
``VerdictArtifact.finalize_to_state_store`` API surface is exercised
end-to-end in :mod:`tests.unit.test_inspect` and friends — this module
is the cheap path-convention smoke test that the brief asks for.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mage.state_store import StateStore


def _git_repo(path: Path) -> Path:
    """Initialize a git repo at ``path`` with identity configured."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def test_inspect_artifact_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    store = StateStore(repo, "feature-artifacts", identity=("T", "t@e"))
    path = "inspect/feature_a/0.yaml"
    store.write(path, b"finding: yes\n")
    assert store.read(path) == b"finding: yes\n"


def test_verdict_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    store = StateStore(repo, "feature-artifacts", identity=("T", "t@e"))
    path = "verdicts/abc123/spec_compliance.yaml"
    store.write(path, b"verdict: pass\n")
    assert store.read(path) == b"verdict: pass\n"


def test_settle_report_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    store = StateStore(repo, "feature-artifacts", identity=("T", "t@e"))
    path = "settle/feature_a.md"
    store.write(path, b"# Settle\n")
    assert store.read(path) == b"# Settle\n"
