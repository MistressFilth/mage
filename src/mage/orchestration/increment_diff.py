"""Increment-relative diff capture.

Replaces the prior `git diff`-based capture in `RealizeStage.run_increment`,
which produced a repository-relative diff (cumulative prior-increment edits,
omitted staged changes, empty for new untracked files). This module
captures a pre-agent snapshot of the project tree and computes an
increment-relative unified diff after the agent runs.

Pure-Python. No subprocess. No events.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pathspec


@dataclass(frozen=True)
class FileSnapshot:
    """The pre-agent state of one path."""

    path: str  # project-relative, forward-slash separated
    exists: bool
    content: bytes | None  # None when not exists
    mode: int | None  # stat.S_IMODE; None when not exists
    truncated: bool = False  # True when content was clipped to MAX_BYTES


MAX_BYTES = 1_000_000  # 1 MB per-file cap
_CONTEXT_LINES = 10
_BINARY_PROBE_BYTES = 8192

_IGNORED_TOP_LEVEL = {".git", ".mage", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _load_gitignore_spec(project_dir: Path) -> pathspec.PathSpec | None:
    """Load .gitignore from project_dir root. Return None if missing or `.gitignore` malformed."""
    gi = project_dir / ".gitignore"
    if not gi.is_file():
        return None
    try:
        return pathspec.PathSpec.from_lines("gitwildmatch", gi.read_text().splitlines())
    except Exception:  # noqa: BLE001 — malformed .gitignore must not break snapshot
        return None


def _walk_files(project_dir: Path, spec: pathspec.PathSpec | None) -> Iterable[Path]:
    """Yield files under project_dir, skipping ignored paths.

    Top-level entries in `_IGNORED_TOP_LEVEL` are always skipped. Paths
    matched by the loaded `.gitignore` spec are also skipped. Symlinks are
    not followed (default `Path.rglob` behavior).
    """
    for entry in project_dir.iterdir():
        if entry.name in _IGNORED_TOP_LEVEL:
            continue
        if entry.is_file():
            yield entry
            continue
        if not entry.is_dir():
            continue
        for path in entry.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(project_dir).as_posix()
            if spec and spec.match_file(rel):
                continue
            yield path


def snapshot_tree(project_dir: Path) -> dict[str, FileSnapshot]:
    """Snapshot every file under project_dir, returning {relpath: FileSnapshot}.

    Skips `.git/`, `.mage/`, and `.gitignore`-matched paths. Files > 1 MB
    are read but truncated to 1 MB with `truncated=True`.
    """
    spec = _load_gitignore_spec(project_dir)
    out: dict[str, FileSnapshot] = {}
    for path in _walk_files(project_dir, spec):
        rel = path.relative_to(project_dir).as_posix()
        try:
            data = path.read_bytes()
            truncated = len(data) > MAX_BYTES
            if truncated:
                data = data[:MAX_BYTES]
            mode = stat.S_IMODE(path.stat().st_mode)
            out[rel] = FileSnapshot(
                path=rel, exists=True, content=data, mode=mode, truncated=truncated
            )
        except OSError:
            # Treat unreadable as exists=True, empty content. Caller may warn.
            out[rel] = FileSnapshot(
                path=rel, exists=True, content=b"", mode=None, truncated=False
            )
    return out


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:_BINARY_PROBE_BYTES]


def _decode_lines(data: bytes) -> list[str]:
    """Decode bytes to lines, tolerating the final missing newline."""
    text = data.decode("utf-8", errors="replace")
    if text and not text.endswith("\n"):
        text += "\n"
    return text.splitlines(keepends=True)


def _diff_one_file(
    project_dir: Path, rel: str, pre: FileSnapshot | None
) -> tuple[str, list[str]]:
    """Return (diff_text_for_this_file, warnings). Empty diff_text = skip."""
    warnings: list[str] = []
    target = project_dir / rel
    try:
        post_exists = target.exists()
    except OSError:
        warnings.append(f"stat failed: {rel}")
        return "", warnings

    if pre is None or not pre.exists:
        if not post_exists:
            warnings.append(f"both pre and post missing: {rel}")
            return "", warnings
        # Addition
        try:
            data = target.read_bytes()
        except OSError as exc:
            warnings.append(f"read failed for addition {rel}: {exc}")
            return "", warnings
        if _is_binary(data):
            return (
                f"diff --git a/{rel} b/{rel}\n"
                f"new file mode 100644\n"
                f"Binary files /dev/null and b/{rel} differ\n"
            ), warnings
        lines = _decode_lines(data)
        header = (
            f"diff --git a/{rel} b/{rel}\n"
            f"new file mode 100644\n"
            f"--- /dev/null\n"
            f"+++ b/{rel}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n"
        )
        body = "".join(f"+{line}" for line in lines)
        return header + body, warnings

    if not post_exists:
        # Deletion
        if pre.content is None:
            warnings.append(f"pre.content missing for deleted file {rel}")
            return "", warnings
        if _is_binary(pre.content):
            return (
                f"diff --git a/{rel} b/{rel}\n"
                f"deleted file mode 100644\n"
                f"Binary files a/{rel} and /dev/null differ\n"
            ), warnings
        lines = _decode_lines(pre.content)
        header = (
            f"diff --git a/{rel} b/{rel}\n"
            f"deleted file mode 100644\n"
            f"--- a/{rel}\n"
            f"+++ /dev/null\n"
            f"@@ -1,{len(lines)} +0,0 @@\n"
        )
        body = "".join(f"-{line}" for line in lines)
        return header + body, warnings

    # Both exist — compare content only. Mode is captured but not diffed.
    try:
        post_data = target.read_bytes()
    except OSError as exc:
        warnings.append(f"read failed for {rel}: {exc}")
        return "", warnings

    pre_bin = pre.content is not None and _is_binary(pre.content)
    post_bin = _is_binary(post_data)

    if pre_bin or post_bin:
        if pre.content == post_data:
            return "", warnings
        return (
            f"diff --git a/{rel} b/{rel}\nBinary files a/{rel} and b/{rel} differ\n"
        ), warnings

    if pre.content == post_data:
        return "", warnings

    pre_lines = _decode_lines(pre.content or b"")  # type: ignore[arg-type]
    post_lines = _decode_lines(post_data)
    import difflib

    udiff = list(
        difflib.unified_diff(
            pre_lines,
            post_lines,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            n=_CONTEXT_LINES,
        )
    )
    return "".join(udiff), warnings


def compute_unified_diff(
    project_dir: Path, paths: list[str], pre: dict[str, FileSnapshot]
) -> tuple[str, list[str]]:
    """Compute increment-relative diff for `paths` vs. `pre`.

    Returns `(diff_text, warnings)`. `diff_text` is the concatenation of
    per-file diffs in `git diff` shape. `warnings` lists paths that were
    skipped (both missing, read error, path traversal).
    """
    chunks: list[str] = []
    warnings: list[str] = []
    for rel in paths:
        # Reject path traversal. Resolve and check containment.
        try:
            resolved = (project_dir / rel).resolve(strict=False)
            if not resolved.is_relative_to(project_dir.resolve()):
                warnings.append(f"path escapes project_dir: {rel}")
                continue
        except OSError:
            warnings.append(f"path resolve failed: {rel}")
            continue

        # Normalize to forward-slash relative path.
        try:
            rel_norm = resolved.relative_to(project_dir.resolve()).as_posix()
        except ValueError:
            rel_norm = rel.replace(os.sep, "/")

        chunk, warns = _diff_one_file(project_dir, rel_norm, pre.get(rel_norm))
        chunks.append(chunk)
        warnings.extend(warns)

    return "".join(chunks), warnings
