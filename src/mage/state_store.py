"""Orphan-branch state storage via git plumbing (P32)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

from mage.host_project_config import MageTomlConfig

__all__ = [
    "DEFAULT_ORPHAN_BRANCH",
    "MageStateConflict",
    "MageStateMigrated",
    "StateStore",
    "state_store_for",
]

DEFAULT_ORPHAN_BRANCH = "feature-artifacts"
_BRANCH_PREFIX = "refs/mage/"
_PATH_PATTERN = re.compile(r"^[a-zA-Z0-9._/-]+$")


class MageStateMigrated(RuntimeError):
    """Legacy `.mage/` state was accessed post-migration.

    Surfaced when a code path tries to read or write the legacy working-tree
    layout after auto-migration has already moved state to the orphan branch.
    Carries the backup timestamp so the caller can prompt for
    ``mage state restore``.
    """

    def __init__(self, backup_timestamp: str, backup_path: Path) -> None:
        self.backup_timestamp = backup_timestamp
        self.backup_path = backup_path
        super().__init__(
            f"Legacy .mage/ state already migrated; backup at {backup_path}. "
            f"Run `mage state restore --from={backup_timestamp}` to revert."
        )


class MageStateConflict(RuntimeError):
    """Ref-update retry failed twice; concurrent contention could not be reconciled."""


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
        input: bytes | None = None,
    ) -> Any: ...


class StateStore:
    """Read/write/delete/list on a project orphan branch.

    Uses ``refs/mage/<branch_name>``. Plumbing-only; never checks the ref out.
    Each write is an atomic CAS via ``git update-ref`` with one retry on
    contention.
    """

    def __init__(
        self,
        project_root: Path,
        branch_name: str,
        *,
        identity: tuple[str, str],
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.branch_name = branch_name
        self.full_ref = f"{_BRANCH_PREFIX}{branch_name}"
        self._identity = identity
        self._runner = command_runner or _default_runner()
        self._bootstrapped = False

    # -- Read API --

    def read(self, relative_path: str) -> bytes:
        _validate_path(relative_path)
        result = self._runner.run(
            ["git", "show", f"{self.full_ref}:{relative_path}"],
            cwd=self.project_root,
        )
        if result.returncode != 0:
            return b""
        return (
            result.stdout.encode("utf-8")
            if isinstance(result.stdout, str)
            else result.stdout
        )

    def exists(self, relative_path: str) -> bool:
        _validate_path(relative_path)
        result = self._runner.run(
            ["git", "ls-tree", self.full_ref, "--", relative_path],
            cwd=self.project_root,
        )
        return bool(result.stdout.strip())

    def list_dir(self, relative_path: str) -> list[str]:
        if relative_path:
            _validate_path(relative_path)
        target = relative_path if relative_path else self.full_ref
        result = self._runner.run(
            ["git", "ls-tree", target],
            cwd=self.project_root,
        )
        if result.returncode != 0:
            return []
        entries = []
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                entries.append(parts[1])
        return entries

    def ref_sha(self) -> str | None:
        result = self._runner.run(
            ["git", "rev-parse", "--verify", self.full_ref],
            cwd=self.project_root,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    # -- Write API --

    def write(self, relative_path: str, data: bytes) -> str:
        _validate_path(relative_path)
        return self._mutate(relative_path, data, delete=False)

    def delete(self, relative_path: str) -> str:
        _validate_path(relative_path)
        return self._mutate(relative_path, None, delete=True)

    # -- Internals --

    def _mutate(self, relative_path: str, data: bytes | None, *, delete: bool) -> str:
        """Apply write or delete with read-modify-write + retry-on-CAS."""
        attempts = 0
        while True:
            attempts += 1
            self._ensure_bootstrapped()
            current_tree = self._read_tree()
            if delete:
                current_tree.pop(relative_path, None)
            else:
                # data is guaranteed non-None in the write branch (write() passes
                # bytes, delete() passes None and takes the branch above).
                assert data is not None
                blob_sha = self._hash_blob(data)
                current_tree[relative_path] = blob_sha
            new_tree_sha = self._mktree(current_tree)
            parent = self.ref_sha() or ""
            new_commit_sha = self._commit_tree(new_tree_sha, parent)
            try:
                self._update_ref(new_commit_sha)
                return new_commit_sha
            except _RefMoved:
                if attempts >= 2:
                    raise MageStateConflict(
                        f"ref {self.full_ref} moved under us twice; cannot reconcile"
                    )
                continue

    def _ensure_bootstrapped(self) -> None:
        if self._bootstrapped:
            return
        if self.ref_sha() is not None:
            self._bootstrapped = True
            return
        empty_tree_sha = self._run(["git", "mktree"], check=True).stdout.strip()
        bootstrap_sha = self._run(
            [
                "git",
                "commit-tree",
                empty_tree_sha,
                "-m",
                "mage: bootstrap state branch",
            ],
            check=True,
        ).stdout.strip()
        self._update_ref(bootstrap_sha)
        self._bootstrapped = True

    def _read_tree(self) -> dict[str, str]:
        result = self._run(["git", "ls-tree", "-r", self.full_ref])
        if result.returncode != 0:
            return {}
        tree: dict[str, str] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                meta, path = parts
                blob_sha = meta.split()[2]
                tree[path] = blob_sha
        return tree

    def _hash_blob(self, data: bytes) -> str:
        # git hash-object -w --stdin writes + prints sha.
        proc = self._run(
            ["git", "hash-object", "-w", "--stdin"],
            check=True,
            input_data=data,
        )
        return proc.stdout.strip()

    def _mktree(self, tree: dict[str, str]) -> str:
        if not tree:
            return self._run(["git", "mktree"], check=True).stdout.strip()
        # Build --read-tree-style input: "<mode> <type> <sha>\t<path>" per line.
        input_str = "\n".join(
            f"100644 blob {sha}\t{path}" for path, sha in sorted(tree.items())
        )
        proc = self._run(["git", "mktree"], check=True, input_str=input_str)
        return proc.stdout.strip()

    def _commit_tree(self, tree_sha: str, parent: str) -> str:
        args = ["git", "commit-tree", tree_sha, "-m", "mage: state update"]
        if parent:
            args += ["-p", parent]
        return self._run(args, check=True).stdout.strip()

    def _update_ref(self, new_sha: str) -> None:
        result = self._run(["git", "update-ref", self.full_ref, new_sha])
        if result.returncode != 0:
            raise _RefMoved(f"ref {self.full_ref} update failed")

    def _run(
        self,
        args: list[str],
        *,
        check: bool = False,
        input_data: bytes | None = None,
        input_str: str | None = None,
    ) -> Any:
        payload: bytes | None = None
        if input_data is not None:
            payload = input_data
        elif input_str is not None:
            payload = input_str.encode("utf-8")
        if payload is not None:
            return self._runner.run(
                args,
                cwd=self.project_root,
                check=check,
                input=payload,
            )
        return self._runner.run(args, cwd=self.project_root, check=check)


class _RefMoved(RuntimeError):
    """Internal signal that update-ref failed (ref moved under us)."""


def _validate_path(relative_path: str) -> None:
    if not relative_path:
        raise ValueError("relative_path must not be empty")
    if len(relative_path) > 4096:
        raise ValueError(f"relative_path length {len(relative_path)} exceeds 4096")
    if relative_path.startswith("/"):
        raise ValueError(f"relative_path must not be absolute: {relative_path!r}")
    if ".." in relative_path.split("/"):
        raise ValueError(f"relative_path must not contain '..': {relative_path!r}")
    if not _PATH_PATTERN.fullmatch(relative_path):
        raise ValueError(
            f"relative_path {relative_path!r} contains invalid characters; "
            "must match [a-zA-Z0-9._/-]+"
        )


def _default_runner() -> CommandRunner:
    """Default CommandRunner: subprocess.run with cwd=project_root."""
    import subprocess as _sp

    class _SubprocessRunner:
        def run(
            self,
            args: list[str],
            *,
            cwd: Path | None = None,
            check: bool = False,
            input: bytes | None = None,
        ) -> Any:
            return _sp.run(
                args,
                cwd=cwd,
                input=input,
                capture_output=True,
                check=check,
            )

    return _SubprocessRunner()


def state_store_for(
    project_root: Path,
    mage_toml: MageTomlConfig | None = None,
    *,
    command_runner: CommandRunner | None = None,
) -> StateStore:
    """Factory: build a StateStore for the given project."""
    branch = mage_toml.orphan_branch if mage_toml else DEFAULT_ORPHAN_BRANCH
    identity = _resolve_identity(project_root)
    return StateStore(
        project_root,
        branch,
        identity=identity,
        command_runner=command_runner,
    )


def _resolve_identity(project_root: Path) -> tuple[str, str]:
    """Resolve git identity: MAGE_GIT_* env > git config > default."""
    name = os.environ.get("MAGE_GIT_NAME")
    email = os.environ.get("MAGE_GIT_EMAIL")
    if name and email:
        return (name, email)
    import subprocess as _sp

    name_result = _sp.run(
        ["git", "config", "user.name"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    email_result = _sp.run(
        ["git", "config", "user.email"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if name_result.returncode == 0 and email_result.returncode == 0:
        n = name_result.stdout.strip()
        e = email_result.stdout.strip()
        if n and e:
            return (n, e)
    return ("mage", "mage@localhost")
