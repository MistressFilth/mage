#!/usr/bin/env python3
"""Read-only repository compliance verifier.

This script enforces the shared repository rules described in
``~/.claude/rules/`` against a repository tree. It is intentionally
read-only: it never mutates Git state or the working tree. The verifier
checks required files, the local-only ignore entries, the bare-repository
worktree topology, the remote URL and fetch refspec, and the absence of
tracked cache artifacts.

The exit status is ``0`` when every check passes and ``1`` with one
diagnostic per failure otherwise. The string ``repository verification
passed`` is printed only on success.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REPO_NAME = "mage"
EXPECTED_REMOTE_URL = f"https://github.com/MistressFilth/{REPO_NAME}.git"
EXPECTED_FETCH_REFSPEC = "+refs/heads/*:refs/heads/*"
EXPECTED_CLAUDE_CONTENTS = "@AGENTS.md\n@AGENTS.local.md\n"
REQUIRED_IGNORE_PARTS = ("AGENTS.local.md", ".claude/settings.local.json")
REQUIRED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "CLAUDE.md",
    "Makefile",
    ".gitignore",
    ".pre-commit-config.yaml",
)
REQUIRED_DOCUMENTATION_FILES = (
    "docs/superpowers/specs",
    "docs/superpowers/plans",
)
FORBIDDEN_TRACKED_PATTERNS = (
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".haileris/",
    ".venv/",
)
GIT_SUBPROCESS_TIMEOUT = 10.0
BARE_DIR_NAME = f"{REPO_NAME}.git"


@dataclass(frozen=True)
class Worktree:
    """A worktree description used by the verifier."""

    path: Path
    branch: str
    upstream: str


class GitProbe(Protocol):
    """Structural protocol the verifier uses to inspect Git state.

    Production runs use a real implementation backed by ``git`` while tests
    inject deterministic fakes. Anything with these five callables is
    accepted without inheritance.
    """

    def has_bare_common_dir(self) -> bool: ...
    def read_remote_url(self) -> str: ...
    def read_fetch_refspec(self) -> str: ...
    def tracked(self) -> tuple[str, ...]: ...
    def list_worktrees(self) -> tuple[Worktree, ...]: ...


def real_git_probe(root: Path) -> GitProbe:
    """Build a GitProbe that shells out to ``git`` for live inspections."""

    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_SUBPROCESS_TIMEOUT,
        )
        return result.stdout.strip()

    def has_bare_common_dir() -> bool:
        return (root.parent / BARE_DIR_NAME).is_dir()

    def read_remote_url() -> str:
        return run("config", "--get", "remote.origin.url")

    def read_fetch_refspec() -> str:
        return run("config", "--get", "remote.origin.fetch")

    def tracked() -> tuple[str, ...]:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_SUBPROCESS_TIMEOUT,
        )
        return tuple(line for line in result.stdout.splitlines() if line)

    def list_worktrees() -> tuple[Worktree, ...]:
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_SUBPROCESS_TIMEOUT,
        )
        return _parse_worktree_porcelain(result.stdout)

    return _CallableProbe(
        has_bare_common_dir=has_bare_common_dir,
        read_remote_url=read_remote_url,
        read_fetch_refspec=read_fetch_refspec,
        tracked=tracked,
        list_worktrees=list_worktrees,
    )


def _parse_worktree_porcelain(output: str) -> tuple[Worktree, ...]:
    """Parse ``git worktree list --porcelain`` into a tuple of Worktrees.

    Records are separated by blank lines. Each record starts with
    ``worktree <path>``, then optionally ``HEAD <sha>`` and ``branch <refs>``.
    Unborn worktrees with no branch are recorded with an empty branch name.
    """
    worktrees: list[Worktree] = []
    current_path: Path | None = None
    current_branch = ""

    def flush() -> None:
        nonlocal current_path, current_branch
        if current_path is not None:
            worktrees.append(
                Worktree(
                    path=current_path,
                    branch=current_branch,
                    upstream=f"origin/{current_branch}" if current_branch else "",
                )
            )
        current_path = None
        current_branch = ""

    for line in output.splitlines():
        if not line.strip():
            flush()
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current_path = Path(value)
        elif key == "branch":
            short = value.removeprefix("refs/heads/")
            current_branch = short
    flush()
    return tuple(worktrees)


@dataclass(frozen=True)
class _CallableProbe:
    """Concrete probe backed by callables; satisfies the GitProbe protocol."""

    has_bare_common_dir: Callable[[], bool]
    read_remote_url: Callable[[], str]
    read_fetch_refspec: Callable[[], str]
    tracked: Callable[[], tuple[str, ...]]
    list_worktrees: Callable[[], tuple[Worktree, ...]]


def build_git_probe(root: Path) -> GitProbe:
    """Default GitProbe factory used by ``main`` and tests."""
    return real_git_probe(root)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def _missing_ignore_entries(ignore_lines: list[str]) -> list[str]:
    """Return ignore entries that are not present verbatim."""
    return [
        required for required in REQUIRED_IGNORE_PARTS if required not in ignore_lines
    ]


def verify_files(root: Path) -> list[str]:
    """Check the on-disk files required by shared repository rules."""
    errors: list[str] = []

    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            errors.append(f"missing required file: {name}")

    claude_text = _read_text(root / "CLAUDE.md")
    if claude_text is None:
        errors.append("missing required file: CLAUDE.md")
    elif claude_text != EXPECTED_CLAUDE_CONTENTS:
        errors.append(
            "CLAUDE.md must contain exactly two lines, "
            f"@AGENTS.md and @AGENTS.local.md; got {claude_text!r}",
        )

    ignore_text = _read_text(root / ".gitignore")
    if ignore_text is None:
        errors.append("missing required file: .gitignore")
    else:
        ignore_lines = [
            line.strip() for line in ignore_text.splitlines() if line.strip()
        ]
        for missing in _missing_ignore_entries(ignore_lines):
            errors.append(
                f".gitignore is missing required ignore entry: {missing}",
            )

    for path in REQUIRED_DOCUMENTATION_FILES:
        if not (root / path).is_dir():
            errors.append(f"missing tracked documentation directory: {path}")

    changelog_text = _read_text(root / "CHANGELOG.md")
    if changelog_text is not None:
        unreleased_count = changelog_text.count("## [Unreleased]")
        if unreleased_count != 1:
            errors.append(
                "CHANGELOG.md must contain exactly one ## [Unreleased] section; "
                f"found {unreleased_count}",
            )

    return errors


def verify_git(root: Path, git: GitProbe) -> list[str]:
    """Check Git-level invariants: URL, refspec, bare dir, tracked files."""
    errors: list[str] = []

    if not root.is_dir():
        errors.append(f"repository root does not exist: {root}")
        return errors

    if not git.has_bare_common_dir():
        errors.append(
            f"missing bare common directory sibling {BARE_DIR_NAME!r} of {root}",
        )

    url = git.read_remote_url()
    if url != EXPECTED_REMOTE_URL:
        errors.append(
            f"remote.origin.url must be {EXPECTED_REMOTE_URL!r}, got {url!r}",
        )

    fetch = git.read_fetch_refspec()
    if fetch != EXPECTED_FETCH_REFSPEC:
        errors.append(
            "remote.origin.fetch must be the direct refspec "
            f"{EXPECTED_FETCH_REFSPEC!r}, got {fetch!r}",
        )

    for path in git.tracked():
        for forbidden in FORBIDDEN_TRACKED_PATTERNS:
            if forbidden in path:
                errors.append(
                    f"tracked artifact must not be committed: {path} "
                    f"(matches forbidden pattern {forbidden!r})",
                )
                break

    return errors


def verify_worktrees(root: Path, worktrees: Iterable[Worktree]) -> list[str]:
    """Check each worktree for sibling layout, path/branch agreement, upstream."""
    errors: list[str] = []
    root_resolved = root.resolve()
    repo_root = root_resolved.parent

    for worktree in worktrees:
        path_resolved = worktree.path.resolve()
        try:
            path_resolved.relative_to(repo_root)
        except ValueError:
            errors.append(
                f"worktree {worktree.path} is not a sibling of {BARE_DIR_NAME}; "
                f"expected a path under {repo_root}",
            )
            continue

        if path_resolved.parent.resolve() != repo_root:
            errors.append(
                f"worktree {worktree.path} must be a sibling of {BARE_DIR_NAME} "
                f"(expected parent {repo_root})",
            )

        if path_resolved.name != worktree.branch:
            errors.append(
                f"worktree directory name {path_resolved.name!r} must equal "
                f"branch name {worktree.branch!r}",
            )

        expected_upstream = f"origin/{worktree.branch}"
        if worktree.upstream != expected_upstream:
            errors.append(
                f"worktree {worktree.path} upstream must be "
                f"{expected_upstream!r}, got {worktree.upstream!r}",
            )

    return errors


def _verify(
    root: Path,
    git: GitProbe,
    worktrees: Iterable[Worktree],
) -> list[str]:
    """Internal helper that fans every check out and concatenates diagnostics."""
    errors: list[str] = []
    errors.extend(verify_files(root))
    errors.extend(verify_git(root, git))
    errors.extend(verify_worktrees(root, worktrees))
    return errors


def verify(root: Path) -> list[str]:
    """Run every verifier and return the combined diagnostics."""
    git = build_git_probe(root)
    worktrees = git.list_worktrees()
    return _verify(root, git, worktrees)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify_repository",
        description="Read-only repository compliance verifier.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root to verify (default: current working directory)",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    root = args.root.resolve()

    errors = verify(root)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(
            f"repository verification failed: {len(errors)} issue(s)",
            file=sys.stderr,
        )
        return 1

    print("repository verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
