"""`mage cosmetic apply --filter` tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mage import cli
from mage.artifacts.mapping import MappingArtifact


def _write_mapping(project_dir: Path, *, feature_id: str, findings: list[dict]) -> Path:
    path = project_dir / "mapping.yaml"
    artifact = MappingArtifact(
        project_id="demo",
        cosmetic_findings=[{**f, "feature_id": feature_id} for f in findings],
    )
    path.write_text(
        yaml.safe_dump(artifact.model_dump(mode="json", by_alias=True), sort_keys=False)
    )
    return path


class _Args:
    def __init__(
        self,
        *,
        feature_id: str,
        project_dir: Path,
        dry_run: bool = False,
        model: str | None = None,
        filter: list[str] | None = None,
    ) -> None:
        self.feature_id = feature_id
        self.project_dir = project_dir
        self.dry_run = dry_run
        self.model = model
        self.filter = filter


@pytest.mark.asyncio
async def test_apply_filter_unknown_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_mapping(
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
    _write_mapping(
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

    async def _fake_apply_for_feature(project_dir, sub_bids, *, dry_run, model):
        seen["project_dir"] = project_dir
        seen["sub_bids"] = sorted(sub_bids)
        seen["dry_run"] = dry_run
        seen["model"] = model
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
            model="test",
            filter=["sub_bid=01JF", "sub_bid=01JF"],  # dedup
        )
    )
    assert rc == 0
    assert seen["sub_bids"] == ["01JF"]
    assert seen["dry_run"] is True
    assert seen["model"] == "test"


@pytest.mark.asyncio
async def test_apply_without_filter_calls_apply_with_all_sub_bids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_mapping(
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

    async def _fake(project_dir, sub_bids, *, dry_run, model):
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
    _write_mapping(
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

    async def _fake(project_dir, sub_bids, *, dry_run, model):
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
