"""`mage state` subcommand: inspect orphan-branch state (P32)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mage.host_project_config import load_mage_toml
from mage.state_migration import restore_from_backup
from mage.state_store import state_store_for

__all__ = [
    "cmd_state_info",
    "cmd_state_ls",
    "cmd_state_restore",
    "cmd_state_show",
    "register",
]


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `mage state` subcommand."""
    p = subparsers.add_parser("state", help="Inspect or restore orphan-branch state.")
    state_sub = p.add_subparsers(dest="state_action", required=True)

    ls = state_sub.add_parser(
        "ls", help="List paths under a directory in the orphan branch."
    )
    ls.add_argument(
        "dir",
        nargs="?",
        default="",
        help="Directory relative to branch root (default: root).",
    )
    ls.set_defaults(func=cmd_state_ls)

    show = state_sub.add_parser("show", help="Materialize a single file to stdout.")
    show.add_argument("path", help="Path relative to branch root.")
    show.set_defaults(func=cmd_state_show)

    info = state_sub.add_parser("info", help="Report branch name, ref SHA, file count.")
    info.set_defaults(func=cmd_state_info)

    restore = state_sub.add_parser(
        "restore", help="Restore state from a .mage.bak.<ts>/ backup."
    )
    restore.add_argument(
        "--from",
        dest="from_ts",
        default=None,
        help="Backup timestamp (default: latest).",
    )
    restore.set_defaults(func=cmd_state_restore)


def cmd_state_ls(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir)
    mage_toml = load_mage_toml(project_dir)
    store = state_store_for(project_dir, mage_toml)
    for entry in store.list_dir(args.dir):
        print(entry)
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir)
    mage_toml = load_mage_toml(project_dir)
    store = state_store_for(project_dir, mage_toml)
    if not store.exists(args.path):
        print(f"error: {args.path} not found in orphan branch", file=sys.stderr)
        return 1
    data = store.read(args.path)
    sys.stdout.buffer.write(data)
    return 0


def cmd_state_info(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir)
    mage_toml = load_mage_toml(project_dir)
    store = state_store_for(project_dir, mage_toml)
    sha = store.ref_sha() or "(none)"
    file_count = len(store.list_dir(""))
    print(f"branch: {store.full_ref}")
    print(f"ref_sha: {sha}")
    print(f"file_count: {file_count}")
    return 0


def cmd_state_restore(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir)
    mage_toml = load_mage_toml(project_dir)
    store = state_store_for(project_dir, mage_toml)
    new_sha = restore_from_backup(project_dir, store, timestamp=args.from_ts)
    print(f"restored; new ref SHA: {new_sha}")
    return 0
