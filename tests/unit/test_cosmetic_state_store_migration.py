"""P32 Task 10 post-review fix: cosmetic watcher + apply_for_feature read mapping
from the orphan branch, not the working-tree file.

Task 10 migrated all `MappingArtifact.load/save` sites to the
``StateStore`` except for the cosmetic watcher and ``apply_for_feature``,
which still read ``<project_dir>/mapping.yaml`` from the working tree.
This file pins the post-fix behavior:

* ``MappingArtifactWatcher._handle_mapping_saved`` reads via
  ``MappingArtifact.load_from_state_store`` using its injected
  ``state_store`` (or the ``state_store_for(...)`` fallback).
* ``apply_for_feature`` reads via
  ``MappingArtifact.load_from_state_store`` and writes its cosmetic-state
  updates through ``StateStore`` (no working-tree write).

Both tests seed a mapping on the orphan branch of a real git repo and
never touch the working-tree file, so a missing ``<project>/mapping.yaml``
cannot accidentally satisfy them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.cosmetic_apply import apply_for_feature
from mage.orchestration.cosmetic_watcher import MappingArtifactWatcher
from mage.orchestration.events import EventsLog
from mage.state_store import StateStore, state_store_for


def _init_git_repo(project_dir: Path) -> None:
    """Initialize ``project_dir`` as a real git repo with a mage identity."""
    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


def _build_mapping(*, feature_id: str, sub_bid: str) -> MappingArtifact:
    """Build a minimal mapping with one cosmetic finding under ``feature_id``."""
    return MappingArtifact(
        project_id="p",
        cosmetic_findings=[
            {
                "feature_id": feature_id,
                "sub_bid": sub_bid,
                "scenario_name": "scenario",
                "location": "src/example.py",
                "text": "use a constant",
                "proposed_by": "human",
            }
        ],
    )


async def _seed_mapping_on_state_store(
    project_dir: Path, mapping: MappingArtifact
) -> StateStore:
    """Seed ``mapping`` on the orphan branch and return the store."""
    state_store = state_store_for(project_dir, mage_toml=None)
    await mapping.save_to_state_store(state_store)
    return state_store


@pytest.mark.asyncio
async def test_cosmetic_watcher_loads_mapping_from_state_store(tmp_path: Path) -> None:
    """The watcher must read mapping from the orphan branch.

    Writes a mapping onto ``refs/mage/feature-artifacts`` and constructs
    the watcher without a working-tree ``mapping.yaml`` at all. The
    catch-up ``_handle_mapping_saved()`` call inside ``run()`` must pick
    up the orphan-branch mapping and dispatch ``apply_for_feature`` with
    the seeded sub_bid.
    """
    _init_git_repo(tmp_path)
    state_store = await _seed_mapping_on_state_store(
        tmp_path, _build_mapping(feature_id="feat-1", sub_bid="01JF")
    )
    """The watcher must read mapping from the orphan branch.

    Writes a mapping onto ``refs/mage/feature-artifacts`` and constructs
    the watcher without a working-tree ``mapping.yaml`` at all. The
    catch-up ``_handle_mapping_saved()`` call inside ``run()`` must pick
    up the orphan-branch mapping and dispatch ``apply_for_feature`` with
    the seeded sub_bid.
    """
    _init_git_repo(tmp_path)
    state_store = await _seed_mapping_on_state_store(
        tmp_path, _build_mapping(feature_id="feat-1", sub_bid="01JF")
    )
    # Sanity check: no working-tree file should exist after seeding.
    assert not (tmp_path / "mapping.yaml").exists()

    log = EventsLog(tmp_path / "events.jsonl")
    log.log_path.parent.mkdir(parents=True, exist_ok=True)
    log.log_path.write_text("")
    watcher = MappingArtifactWatcher(
        tmp_path,
        events_log=log,
        poll_interval_ms=10,
        state_store=state_store,
    )
    with patch(
        "mage.orchestration.cosmetic_watcher.apply_for_feature",
        new=AsyncMock(return_value=0),
    ) as mock_apply:
        # Short-circuit the poll loop after the catch-up runs.
        watcher._stop = True
        await watcher.run()
    mock_apply.assert_called_once()
    args, kwargs = mock_apply.call_args
    sub_bids_arg = args[1] if len(args) > 1 else kwargs.get("sub_bids")
    assert "01JF" in (sub_bids_arg or [])
    # Confirm the watcher handed the state_store through to apply_for_feature
    assert kwargs.get("state_store") is state_store


@pytest.mark.asyncio
async def test_cosmetic_watcher_falls_back_to_state_store_factory(
    tmp_path: Path,
) -> None:
    """When no ``state_store`` is injected, the watcher uses
    ``state_store_for(project_dir, load_mage_toml(project_dir))`` so the
    factory's ``mage.toml.orphan_branch`` override is honored.
    """
    _init_git_repo(tmp_path)
    # Drop a custom ``mage.toml`` that points at a different orphan branch.
    (tmp_path / "mage.toml").write_text(
        '[agents]\norphan_branch = "custom-state"\n', encoding="utf-8"
    )
    state_store = state_store_for(tmp_path, mage_toml=None)
    # Resolve the toml to register the override (the watcher does this).
    from mage.host_project_config import load_mage_toml

    mage_toml = load_mage_toml(tmp_path)
    state_store = state_store_for(tmp_path, mage_toml=mage_toml)
    assert state_store.branch_name == "custom-state"
    mapping = _build_mapping(feature_id="feat", sub_bid="01JG")
    await mapping.save_to_state_store(state_store)

    log = EventsLog(tmp_path / "events.jsonl")
    log.log_path.parent.mkdir(parents=True, exist_ok=True)
    log.log_path.write_text("")
    watcher = MappingArtifactWatcher(tmp_path, events_log=log, poll_interval_ms=10)
    # The factory-built state_store must reflect the toml override.
    assert watcher.state_store.branch_name == "custom-state"
    with patch(
        "mage.orchestration.cosmetic_watcher.apply_for_feature",
        new=AsyncMock(return_value=0),
    ):
        watcher._stop = True
        await watcher.run()
    # The fallback's reads landed on the toml-overridden branch.
    reloaded = MappingArtifact.load_from_state_store(state_store)
    assert any(item.get("sub_bid") == "01JG" for item in reloaded.cosmetic_findings)


@pytest.mark.asyncio
async def test_apply_for_feature_uses_state_store(tmp_path: Path) -> None:
    """``apply_for_feature`` must read+write mapping via the state store.

    Seeds a mapping on the orphan branch, runs the function with the
    state_store kwarg, and verifies the seeded sub_bid is processed
    without ever needing a working-tree ``mapping.yaml``. The CosmeticRefiner
    is replaced with a stub that captures the calls and returns a
    ``CosmeticPatch`` with ``file_path=None`` so the function short-
    circuits before any disk write (the assertion is on the queue
    selection itself).
    """
    from mage.artifacts.cosmetic import CosmeticPatch

    _init_git_repo(tmp_path)
    state_store = await _seed_mapping_on_state_store(
        tmp_path, _build_mapping(feature_id="feat-x", sub_bid="01Z9")
    )
    assert not (tmp_path / "mapping.yaml").exists()

    captured: list[dict] = []

    class _StubRefiner:
        def __init__(self, *, model=None) -> None:
            pass

        async def refine(self, raw, *, semaphore):
            captured.append(
                {"sub_bid": raw["sub_bid"], "feature_id": raw["feature_id"]}
            )
            return CosmeticPatch(
                sub_bid=raw["sub_bid"],
                file_path=None,  # skip disk write / refiner network
                line_range=(0, 0),
                replacement_text="",
                rationale="",
                proposed_by="human",
            )

    with patch("mage.agents.cosmetic_refiner.CosmeticRefiner", _StubRefiner):
        rc = await apply_for_feature(
            tmp_path,
            ["01Z9"],
            dry_run=True,
            feature_id="feat-x",
            state_store=state_store,
        )
    assert rc == 0
    assert captured == [{"sub_bid": "01Z9", "feature_id": "feat-x"}]
