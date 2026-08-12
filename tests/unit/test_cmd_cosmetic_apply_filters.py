"""`mage cosmetic apply --filter` tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from mage import cli
from mage.artifacts.mapping import MappingArtifact


async def _write_mapping(
    project_dir: Path, *, feature_id: str, findings: list[dict]
) -> Path:
    """Write a mapping.yaml AND seed it onto the orphan branch (P32).

    The CLI reads through the state store, so the canonical seed must
    land on the orphan branch. The working-tree file is also kept for
    parity with the pre-migration layout.
    """
    import asyncio

    path = project_dir / "mapping.yaml"
    artifact = MappingArtifact(
        project_id="demo",
        cosmetic_findings=[{**f, "feature_id": feature_id} for f in findings],
    )
    path.write_text(
        yaml.safe_dump(artifact.model_dump(mode="json", by_alias=True), sort_keys=False)
    )
    # P32: seed the orphan branch. init git first.

    def _check_git() -> bool:
        return (
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=project_dir,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    def _init_git() -> None:
        subprocess.run(
            ["git", "init"], cwd=project_dir, check=True, capture_output=True
        )
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

    has_git = await asyncio.to_thread(_check_git)
    if not has_git:
        await asyncio.to_thread(_init_git)
    from mage.state_store import StateStore

    state_store = StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))
    await artifact.save_to_state_store(state_store)
    return path


class _Args:
    def __init__(
        self,
        *,
        feature_id: str,
        project_dir: Path,
        dry_run: bool = False,
        filter: list[str] | None = None,
    ) -> None:
        self.feature_id = feature_id
        self.project_dir = project_dir
        self.dry_run = dry_run
        self.filter = filter


@pytest.mark.asyncio
async def test_apply_filter_unknown_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "s",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
            }
        ],
    )
    rc = await cli.cmd_cosmetic_apply(
        _Args(
            feature_id="feat",
            project_dir=tmp_path,
            filter=["sub_bid=01ZZ"],
        )
    )
    assert rc == 2


@pytest.mark.asyncio
async def test_apply_filter_narrows_calls_apply_for_feature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrowed sub_bid set is what reaches apply_for_feature."""
    await _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "s1",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
            {
                "sub_bid": "01JG",
                "scenario_name": "s2",
                "location": "src/b.py",
                "text": "y",
                "proposed_by": "increment_quality",
            },
        ],
    )
    seen: dict = {}

    async def _fake_apply_for_feature(
        project_dir, sub_bids, *, dry_run, feature_id=None
    ):
        seen["project_dir"] = project_dir
        seen["sub_bids"] = sorted(sub_bids)
        seen["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(
        "mage.orchestration.cosmetic_apply.apply_for_feature",
        _fake_apply_for_feature,
    )
    rc = await cli.cmd_cosmetic_apply(
        _Args(
            feature_id="feat",
            project_dir=tmp_path,
            dry_run=True,
            filter=["sub_bid=01JF", "sub_bid=01JF"],  # dedup
        )
    )
    assert rc == 0
    assert seen["sub_bids"] == ["01JF"]
    assert seen["dry_run"] is True


@pytest.mark.asyncio
async def test_apply_without_filter_calls_apply_with_all_sub_bids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "s1",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
            {
                "sub_bid": "01JG",
                "scenario_name": "s2",
                "location": "src/b.py",
                "text": "y",
                "proposed_by": "increment_quality",
            },
        ],
    )
    seen: dict = {}

    async def _fake(project_dir, sub_bids, *, dry_run, feature_id=None):
        seen["sub_bids"] = sorted(sub_bids)
        return 0

    monkeypatch.setattr(
        "mage.orchestration.cosmetic_apply.apply_for_feature",
        _fake,
    )
    rc = await cli.cmd_cosmetic_apply(_Args(feature_id="feat", project_dir=tmp_path))
    assert rc == 0
    assert seen["sub_bids"] == ["01JF", "01JG"]


@pytest.mark.asyncio
async def test_apply_does_not_crash_on_null_sub_bid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An entry with `sub_bid: None` must not crash `apply` (Crit. 2).

    The apply set is built from non-empty strings only; the null entry is
    silently dropped so apply_for_feature never sees a None sub_bid.
    """
    await _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": None,
                "scenario_name": "null",
                "location": "src/n.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
            {
                "sub_bid": "01JF",
                "scenario_name": "ok",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
        ],
    )
    seen: dict = {}

    async def _fake(project_dir, sub_bids, *, dry_run, feature_id=None):
        seen["sub_bids"] = list(sub_bids)
        return 0

    monkeypatch.setattr(
        "mage.orchestration.cosmetic_apply.apply_for_feature",
        _fake,
    )
    rc = await cli.cmd_cosmetic_apply(_Args(feature_id="feat", project_dir=tmp_path))
    assert rc == 0
    # Only the well-formed entry reaches apply_for_feature
    assert seen["sub_bids"] == ["01JF"]


@pytest.mark.asyncio
async def test_apply_passes_feature_id_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`apply` must forward the positional feature_id (Important #3).

    apply_for_feature now takes feature_id as a kwarg so the watcher
    can scope its fan-out per-feature. The CLI must pass the same
    feature_id the user provided so any future feature-scoped logic
    in apply_for_feature sees the correct value.
    """
    await _write_mapping(
        tmp_path,
        feature_id="feat-a",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "s",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
        ],
    )
    seen: dict = {}

    async def _fake(
        project_dir,
        sub_bids,
        *,
        dry_run,
        feature_id=None,
    ):
        seen["feature_id"] = feature_id
        seen["sub_bids"] = list(sub_bids)
        return 0

    monkeypatch.setattr(
        "mage.orchestration.cosmetic_apply.apply_for_feature",
        _fake,
    )
    rc = await cli.cmd_cosmetic_apply(_Args(feature_id="feat-a", project_dir=tmp_path))
    assert rc == 0
    assert seen["feature_id"] == "feat-a"
    assert seen["sub_bids"] == ["01JF"]


@pytest.mark.asyncio
async def test_apply_for_feature_narrows_by_feature_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`apply_for_feature(feature_id=...)` skips other features' sub_bids.

    Important #3: when a sub_bid exists in two features, the
    feature-scoped apply must not pick up the other feature's entry.
    P32: the mapping now lives on the orphan branch, so we seed it
    via ``MappingArtifact.save_to_state_store`` and the function picks
    it up via ``state_store_for(...)``.
    """
    from mage.orchestration.cosmetic_apply import apply_for_feature
    from mage.state_store import state_store_for

    project_dir = tmp_path
    # P32: a real git repo so the orphan branch can be created.
    from tests.conftest import init_git_repo

    init_git_repo(project_dir)
    mapping = MappingArtifact(
        project_id="demo",
        cosmetic_findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "in-feat-a",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
                "feature_id": "feat-a",
            },
            {
                "sub_bid": "01JF",
                "scenario_name": "in-feat-b",
                "location": "src/b.py",
                "text": "y",
                "proposed_by": "increment_quality",
                "feature_id": "feat-b",
            },
        ],
    )
    state_store = state_store_for(project_dir, mage_toml=None)
    await mapping.save_to_state_store(state_store)

    captured: list[str] = []

    class _StubRefiner:
        def __init__(self, *, model=None) -> None:
            pass

        async def refine(self, raw, *, semaphore):
            from mage.artifacts.cosmetic import CosmeticPatch

            captured.append(raw["scenario_name"])
            return CosmeticPatch(
                sub_bid=raw["sub_bid"],
                file_path=None,
                line_range=(0, 0),
                replacement_text="",
                rationale="",
                proposed_by="increment_quality",
            )

    monkeypatch.setattr("mage.agents.cosmetic_refiner.CosmeticRefiner", _StubRefiner)
    rc = await apply_for_feature(
        project_dir,
        ["01JF"],
        dry_run=True,
        feature_id="feat-a",
    )
    assert rc == 0
    # Only feat-a's entry was processed
    assert captured == ["in-feat-a"]
