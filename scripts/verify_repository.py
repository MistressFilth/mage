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
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


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
)
FORBIDDEN_TRACKED_PATTERNS = (
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".haileris/",
    ".venv/",
)


@dataclass(frozen=True)
class Worktree:
    """A worktree description used by the verifier."""

    path: Path
    branch: str
    upstream: str


@dataclass(frozen=True)
class GitProbe:
    """A small protocol surface the verifier uses to inspect Git state.

    The verifier depends only on the protocol — production runs use a real
    implementation backed by ``git`` while tests inject deterministic fakes.
    """

    is_bare_directory: Callable[[], bool]
    has_bare_common_dir: Callable[[], bool]
    read_remote_url: Callable[[], str]
    read_fetch_refspec: Callable[[], str]
    tracked: Callable[[], tuple[str, ...]]


def real_git_probe(root: Path) -> GitProbe:
    """Build a GitProbe that shells out to ``git`` for live inspections."""

    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()

    def is_bare_directory() -> bool:
        return run("rev-parse", "--is-bare-repository") == "true"

    def has_bare_common_dir() -> bool:
        return (root.parent / f"{REPO_NAME}.git").is_dir()

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
        )
        return tuple(line for line in result.stdout.splitlines() if line)

    return GitProbe(
        is_bare_directory=is_bare_directory,
        has_bare_common_dir=has_bare_common_dir,
        read_remote_url=read_remote_url,
        read_fetch_refspec=read_fetch_refspec,
        tracked=tracked,
    )


def build_git_probe(root: Path) -> GitProbe:
    """Default GitProbe factory used by ``main`` and tests."""
    return real_git_probe(root)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def _gitignore_missing(ignore_text: str | None) -> list[str]:
    if ignore_text is None:
        return list(REQUIRED_IGNORE_PARTS)
    missing: list[str] = []
    for required in REQUIRED_IGNORE_PARTS:
        pattern = re.compile(rf"(?m)^(?:{re.escape(required)}|\*\*{re.escape(required)}|/.*{re.escape(required)})$")
        if not pattern.search(ignore_text):
            missing.append(required)
    return missing


def verify_files(root: Path) -> list[str]:
    """Check the on-disk files required by shared repository rules."""
    errors: list[str] = []

    for name in REQUIRED_FILES:
        path = root / name
        if not path.is_file():
            errors.append(f"missing required file: {name}")
            continue

    claude_text = _read_text(root / "CLAUDE.md")
    if claude_text is None:
        errors.append("missing required file: CLAUDE.md")
    elif claude_text != EXPECTED_CLAUDE_CONTENTS:
        errors.append(
            "CLAUDE.md must contain exactly '@AGENTS.md\\n@AGENTS.local.md\\n' "
            "with no other content",
        )

    ignore_text = _read_text(root / ".gitignore")
    if ignore_text is None:
        errors.append("missing required file: .gitignore")
    else:
        for missing in _gitignore_missing(ignore_text):
            errors.append(
                f".gitignore is missing required ignore entry: {missing}",
            )

    return errors


def verify_git(root: Path, git: GitProbe) -> list[str]:
    """Check Git-level invariants: URL, refspec, bare dir, tracked files."""
    errors: list[str] = []

    if not root.is_dir():
        errors.append(f"repository root does not exist: {root}")
        return errors

    if not git.is_bare_directory() and not git.has_bare_common_dir():
        errors.append(
            f"missing bare common directory sibling of {root}",
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
                f"worktree {worktree.path} is not a sibling of "
                f"{f'{REPO_NAME}.git'}; expected a path under {repo_root}",
            )
            continue

        if path_resolved.parent.resolve() != repo_root:
            errors.append(
                f"worktree {worktree.path} must be a sibling of {f'{REPO_NAME}.git'} "
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


def verify(root: Path, git: GitProbe | None = None) -> list[str]:
    """Run every verifier and return the combined diagnostics."""
    if git is None:
        git = build_git_probe(root)
    errors: list[str] = []
    errors.extend(verify_files(root))
    errors.extend(verify_git(root, git))
    return errors


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

    git = build_git_probe(root)
    errors = verify(root, git)

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
