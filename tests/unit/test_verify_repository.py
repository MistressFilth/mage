"""Tests for the read-only repository compliance verifier.

These tests use temporary repositories so no real Git state is touched. Git
information is supplied through a ``GitProbe``-compatible object so tests
stay deterministic and avoid spawning subprocesses.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest
from verify_repository import (  # ty: ignore[unresolved-import]
    Worktree,
    _parse_worktree_porcelain,
    build_git_probe,
    main,
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
    ".pre-commit-config.yaml": "repos: []\n",
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
    (root / "docs" / "superpowers" / "specs").mkdir(parents=True)
    (root / "docs" / "superpowers" / "plans").mkdir(parents=True)
    ignore_lines = [
        "__pycache__/",
        "*.pyc",
        "*.haileris/",
        *REQUIRED_GITIGNORE_PARTS,
    ]
    (root / ".gitignore").write_text("\n".join(ignore_lines) + "\n")
    (root.parent / bare_dir).mkdir(exist_ok=True)


class FakeProbe:
    """Minimal duck-typed GitProbe for tests."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        bare_dir: str = "repo.git",
        url: str = "https://github.com/MistressFilth/mage.git",
        fetch: str = "+refs/heads/*:refs/heads/*",
        tracked_files: tuple[str, ...] = (),
        worktrees: Iterable[Worktree] = (),
    ) -> None:
        self._root = root
        self._bare_dir = bare_dir
        self._url = url
        self._fetch = fetch
        self._tracked = tracked_files
        self._worktrees = tuple(worktrees)

    def has_bare_common_dir(self) -> bool:
        return bool(self._root and (self._root.parent / self._bare_dir).exists())

    def read_remote_url(self) -> str:
        return self._url

    def read_fetch_refspec(self) -> str:
        return self._fetch

    def tracked(self) -> tuple[str, ...]:
        return self._tracked

    def list_worktrees(self) -> tuple[Worktree, ...]:
        return self._worktrees


def test_accepts_required_files_and_exact_claude_references(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = FakeProbe(root=tmp_path, bare_dir="repo.git")
    errors = verify_with_probe(tmp_path, probe)
    assert errors == []


def test_rejects_missing_local_ignore_entries(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    probe = FakeProbe(root=tmp_path, bare_dir="repo.git")
    errors = verify_with_probe(tmp_path, probe)
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


def test_verify_files_rejects_missing_tracked_documentation(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / "docs" / "superpowers" / "plans").rmdir()
    errors = verify_files(tmp_path)
    assert any("docs/superpowers/plans" in error for error in errors)


def test_verify_files_rejects_duplicate_unreleased_sections(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [Unreleased]\n"
    )
    errors = verify_files(tmp_path)
    assert any("exactly one" in error for error in errors)


def test_verify_files_accepts_valid_tree(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    assert verify_files(tmp_path) == []


def test_verify_files_rejects_missing_pre_commit_config(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").unlink()
    errors = verify_files(tmp_path)
    assert any(".pre-commit-config.yaml" in error for error in errors)


def test_claude_diagnostic_uses_repr_for_newline_safety(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n# extra junk\n")
    errors = verify_files(tmp_path)
    assert any("\\n" in error for error in errors)


def test_verify_files_rejects_glob_ignore_entry(tmp_path: Path) -> None:
    """The rule requires the literal line, not an ``**/foo`` pattern."""
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "**/AGENTS.local.md\n**/.claude/settings.local.json\n"
    )
    errors = verify_files(tmp_path)
    assert any("AGENTS.local.md" in error for error in errors)
    assert any(".claude/settings.local.json" in error for error in errors)


def test_verify_git_accepts_compliant_probe(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = FakeProbe(root=tmp_path, bare_dir="repo.git")
    assert verify_git(tmp_path, probe) == []


def test_verify_git_rejects_wrong_url(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = FakeProbe(
        root=tmp_path,
        bare_dir="repo.git",
        url="git@github.com:MistressFilth/mage.git",
    )
    errors = verify_git(tmp_path, probe)
    assert any("remote.origin.url" in error for error in errors)


def test_verify_git_rejects_tracked_cache_artifact(tmp_path: Path) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = FakeProbe(
        root=tmp_path,
        bare_dir="repo.git",
        tracked_files=("src/mage/__pycache__/x.pyc",),
    )
    errors = verify_git(tmp_path, probe)
    assert any("__pycache__" in error for error in errors)


def test_verify_git_rejects_missing_bare_dir(tmp_path: Path) -> None:
    """Files needed for the file check, but the bare common dir is absent."""
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    for name, contents in REQUIRED_FILES.items():
        (root / name).write_text(contents)
    (root / ".gitignore").write_text("\n".join(REQUIRED_GITIGNORE_PARTS) + "\n")
    # Do NOT create the bare common dir.
    probe = FakeProbe(root=root, bare_dir="never-created.git")
    errors = verify_git(root, probe)
    assert any("bare common directory" in error for error in errors)


def test_verify_worktrees_accepts_sibling_layout(tmp_path: Path) -> None:
    sibling = tmp_path.parent / "feature-x"
    worktree = Worktree(
        path=sibling,
        branch="feature-x",
        upstream="origin/feature-x",
    )
    assert verify_worktrees(tmp_path, [worktree]) == []


def test_verify_worktrees_skips_bare_common_dir_entry(tmp_path: Path) -> None:
    """The bare common dir itself appears in porcelain with no branch."""
    from verify_repository import BARE_DIR_NAME  # ty: ignore[unresolved-import]

    bare = tmp_path.parent / BARE_DIR_NAME
    worktree = Worktree(
        path=bare,
        branch="",
        upstream="",
    )
    assert verify_worktrees(tmp_path, [worktree]) == []


def test_verify_worktrees_skips_locked_worktree(tmp_path: Path) -> None:
    """Active agents hold a locked worktree that cannot be moved."""
    nested = tmp_path / ".claude" / "worktrees" / "agent-x"
    nested.mkdir(parents=True)
    worktree = Worktree(
        path=nested,
        branch="worktree-agent-x",
        upstream="",
        locked=True,
    )
    assert verify_worktrees(tmp_path, [worktree]) == []


def test_verify_worktrees_skips_upstream_when_no_remote_ref(tmp_path: Path) -> None:
    """Branches without origin/<branch> are exempt from the upstream check."""
    sibling = tmp_path.parent / "plan-99-local-only"
    worktree = Worktree(
        path=sibling,
        branch="plan-99-local-only",
        upstream="",
        has_remote=False,
    )
    assert verify_worktrees(tmp_path, [worktree]) == []


def test_verify_calls_worktree_discovery(tmp_path: Path) -> None:
    """``verify`` must call ``list_worktrees`` and surface its diagnostics."""
    write_valid_repository_fixture(tmp_path)
    nested = tmp_path / ".claude" / "worktrees" / "agent-x"
    nested.mkdir(parents=True)
    probe = FakeProbe(
        root=tmp_path,
        bare_dir="repo.git",
        worktrees=[Worktree(path=nested, branch="agent-x", upstream="origin/agent-x")],
    )
    errors = verify_with_probe(tmp_path, probe)
    assert any("sibling" in error for error in errors)


def test_parse_worktree_porcelain_handles_typical_output(tmp_path: Path) -> None:
    output = (
        "worktree /home/dev/mage/main\n"
        "HEAD abcdef0123456789\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /home/dev/mage/feature-x\n"
        "HEAD 0011223344556677\n"
        "branch refs/heads/feature-x\n"
        "\n"
    )
    parsed = _parse_worktree_porcelain(output, frozenset({"main", "feature-x"}))
    assert parsed == (
        Worktree(
            path=Path("/home/dev/mage/main"),
            branch="main",
            upstream="origin/main",
        ),
        Worktree(
            path=Path("/home/dev/mage/feature-x"),
            branch="feature-x",
            upstream="origin/feature-x",
        ),
    )


def test_parse_worktree_porcelain_marks_branches_without_remote(tmp_path: Path) -> None:
    output = (
        "worktree /home/dev/mage/main\n"
        "HEAD abcdef0123456789\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /home/dev/mage/plan-99-local-only\n"
        "HEAD 0011223344556677\n"
        "branch refs/heads/plan-99-local-only\n"
        "\n"
    )
    parsed = _parse_worktree_porcelain(output, frozenset({"main"}))
    assert parsed == (
        Worktree(
            path=Path("/home/dev/mage/main"),
            branch="main",
            upstream="origin/main",
        ),
        Worktree(
            path=Path("/home/dev/mage/plan-99-local-only"),
            branch="plan-99-local-only",
            upstream="",
            has_remote=False,
        ),
    )


def test_parse_worktree_porcelain_records_locked_worktree(tmp_path: Path) -> None:
    output = (
        "worktree /home/dev/mage/main\n"
        "HEAD abcdef0123456789\n"
        "branch refs/heads/main\n"
        "locked agent aaa\n"
        "\n"
    )
    parsed = _parse_worktree_porcelain(output, frozenset({"main"}))
    assert parsed == (
        Worktree(
            path=Path("/home/dev/mage/main"),
            branch="main",
            upstream="origin/main",
            locked=True,
        ),
    )


def test_parse_worktree_porcelain_handles_unborn_records(tmp_path: Path) -> None:
    output = "worktree /home/dev/mage/draft\n\n"
    parsed = _parse_worktree_porcelain(output)
    assert parsed == (
        Worktree(
            path=Path("/home/dev/mage/draft"),
            branch="",
            upstream="",
            has_remote=False,
        ),
    )


def test_main_exits_zero_when_compliant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_repository_fixture(tmp_path)
    probe = FakeProbe(root=tmp_path, bare_dir="repo.git")
    monkeypatch.setattr("verify_repository.build_git_probe", lambda r: probe)
    rc = main(["--root", str(tmp_path)])
    assert rc == 0


def test_main_exits_one_when_noncompliant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    probe = FakeProbe(root=tmp_path, bare_dir="repo.git")
    monkeypatch.setattr("verify_repository.build_git_probe", lambda r: probe)
    rc = main(["--root", str(tmp_path)])
    assert rc == 1


def test_main_uses_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real probe must pass a timeout to subprocess.run."""
    captured: dict[str, object] = {}

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(*args: object, **kwargs: object) -> _FakeCompleted:
        captured["timeout"] = kwargs.get("timeout")
        captured["args"] = args
        return _FakeCompleted()

    monkeypatch.setattr("verify_repository.subprocess.run", fake_run)
    probe = build_git_probe(Path.cwd())
    probe.read_remote_url()
    assert captured["timeout"] is not None
    assert captured["timeout"] == 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def verify_with_probe(root: Path, probe: FakeProbe) -> list[str]:
    """Run ``verify`` with a stub probe so tests stay deterministic."""
    from verify_repository import _verify  # ty: ignore[unresolved-import]

    return _verify(root, probe, probe.list_worktrees())
