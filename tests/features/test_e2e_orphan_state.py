"""End-to-end test: StateStore reads/writes against a real git repo (P32)."""

from __future__ import annotations

from pathlib import Path

from mage.host_project_config import MageTomlConfig
from mage.state_store import state_store_for
from tests.conftest import init_git_repo


def test_state_store_roundtrip_via_real_git(tmp_path: Path) -> None:
    """StateStore reads/writes commit objects on a real git orphan ref."""
    init_git_repo(tmp_path)
    store = state_store_for(tmp_path, MageTomlConfig())
    sha = store.write("inspect/feature_a/0.yaml", b"finding: yes\n")
    assert sha and len(sha) >= 7  # git short SHA
    assert store.read("inspect/feature_a/0.yaml") == b"finding: yes\n"
    assert store.exists("inspect/feature_a/0.yaml")


def test_state_store_list_dir_via_real_git(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    store = state_store_for(tmp_path, MageTomlConfig())
    store.write("inspect/fid/0.yaml", b"a\n")
    store.write("verdicts/hash/spec_compliance.yaml", b"b\n")
    entries = store.list_dir("")
    assert "inspect" in entries
    assert "verdicts" in entries


def test_state_store_bootstrap_is_idempotent(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    store = state_store_for(tmp_path, MageTomlConfig())
    assert store.ref_sha() is None
    sha = store.write("a.yaml", b"x\n")
    # Bootstrap commit + first write commit both exist; ref points at the latter.
    assert store.ref_sha() == sha
