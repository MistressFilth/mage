"""Tests for the read-only repository compliance verifier.

These tests use temporary repositories so no real Git state is touched. Git
information is supplied through the ``GitProbe`` protocol so tests stay
deterministic and avoid spawning subprocesses.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_repository import (  # noqa: E402  (sys.path tweak above)
    GitProbe,
    Worktree,
    verify,
    verify_files,
    verify_git,
    verify_worktrees,
)


REQUIRED_FILES: dict[str, str] = {
    "README.md": "# mage\n",
    "CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n",
    "AGENTS.md": "# AGENTS.md\n",
    "CLAUDE.md": "@AGENTS.md\n@AGENTS.local.md\n",
    "Makefile": ".DEFAULT_GOAL := help\n",
}

REQUIRED_GITIGNORE_PARTS = (
    "AGENTS.local.md",
    ".claude/settings.local.json",
)


def write_valid_repository_fixture(root: Path, *, bare_dir: str = "repo.git") -> None:
    """Create a minimal valid repository tree under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    for name, contents in REQUIRED_FILES.items():
        (root / name).write_text(contents)
    ignore_lines = [
        "__pycache__/",
        "*.pyc",
        "*.haileris/",
        "",
        *REQUIRED_GITIGNORE_PARTS,
    ]
    (root / ".gitignore").write_text("\n".join(ignore_lines) + "\n")
    (root.parent / bare_dir).mkdir(exist_ok=True)


def make_git_probe(
    *,
    root: Path | None = None,
    url: str = "https://github.com/MistressFilth/mage.git",
    fetch: str = "+refs/heads/*:refs/heads/*",
    bare_dir: str = "repo.git",
    tracked_files: tuple[str, ...] = (),
) -> GitProbe:
    """Build a GitProbe with the given values; all defaults are compliant."""

    def is_bare_directory() -> bool:
        return bool(root and (root.parent / bare_dir).exists())

    def has_bare_common_dir() -> bool:
        return bool(root and (root.parent / bare_dir).exists())

    def read_remote_url() -> str:
        return url

    def read_fetch_refspec() -> str:
        return fetch

    def tracked() -> tuple[str, ...]:
        return tracked_files

    return GitProbe(
        is_bare_directory=is_bare_directory,
        has_bare_common_dir=has_bare_common_dir,
        read_remote_url=read_remote_url,
        read_fetch_refspec=read_fetch_refspec,
        tracked=tracked,
    )


def test_accepts_required_files_and_exact_claude_references(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = make_git_probe(root=tmp_path, bare_dir="repo.git")
    errors = verify(tmp_path, probe)
    assert errors == []


def test_rejects_missing_local_ignore_entries(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    probe = make_git_probe(root=tmp_path, bare_dir="repo.git")
    errors = verify(tmp_path, probe)
    assert any("AGENTS.local.md" in error for error in errors)


def test_rejects_wrong_worktree_path_and_upstream(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    bad_worktree = Worktree(
        path=tmp_path / ".claude" / "worktrees" / "x",
        branch="feature-x",
        upstream="origin/main",
    )
    errors = verify_worktrees(tmp_path, [bad_worktree])
    joined = " ".join(errors)
    assert "sibling" in joined
    assert "origin/feature-x" in joined


def test_verify_files_accepts_valid_tree(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    assert verify_files(tmp_path) == []


def test_verify_files_rejects_wrong_claude_references(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n")
    errors = verify_files(tmp_path)
    assert any("CLAUDE.md" in error for error in errors)


def test_verify_git_accepts_compliant_probe(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = make_git_probe(root=tmp_path, bare_dir="repo.git")
    assert verify_git(tmp_path, probe) == []


def test_verify_git_rejects_wrong_url(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = make_git_probe(
        root=tmp_path,
        bare_dir="repo.git",
        url="git@github.com:MistressFilth/mage.git",
    )
    errors = verify_git(tmp_path, probe)
    assert any("remote.origin.url" in error for error in errors)


def test_verify_git_rejects_tracked_cache_artifact(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = make_git_probe(
        root=tmp_path,
        bare_dir="repo.git",
        tracked_files=("src/mage/__pycache__/x.pyc",),
    )
    errors = verify_git(tmp_path, probe)
    assert any("__pycache__" in error or "tracked" in error for error in errors)


def test_verify_worktrees_accepts_sibling_layout(tmp_path: Path) -> None:
    sibling = tmp_path.parent / "feature-x"
    worktree = Worktree(
        path=sibling,
        branch="feature-x",
        upstream="origin/feature-x",
    )
    assert verify_worktrees(tmp_path, [worktree]) == []


def test_main_exits_zero_when_compliant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = make_git_probe(root=tmp_path, bare_dir="repo.git")
    monkeypatch.setattr("verify_repository.build_git_probe", lambda r: probe)
    rc = verify_repository_main(["--root", str(tmp_path)])  # type: ignore[name-defined]
    assert rc == 0


def test_main_exits_one_when_noncompliant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    probe = make_git_probe(root=tmp_path, bare_dir="repo.git")
    monkeypatch.setattr("verify_repository.build_git_probe", lambda r: probe)
    rc = verify_repository_main(["--root", str(tmp_path)])  # type: ignore[name-defined]
    assert rc == 1


# Late import helper so monkeypatch above targets the real module object.
def verify_repository_main(argv: list[str]) -> int:
    from verify_repository import main

    return main(argv)
