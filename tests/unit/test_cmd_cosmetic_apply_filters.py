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

    async def _fake_apply_for_feature(
        project_dir, sub_bids, *, dry_run, model, feature_id=None
    ):
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

    async def _fake(project_dir, sub_bids, *, dry_run, model, feature_id=None):
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

    async def _fake(project_dir, sub_bids, *, dry_run, model, feature_id=None):
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
    _write_mapping(
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
        model,
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
async def test_apply_for_feature_narrows_by_feature_id(tmp_path: Path) -> None:
    """`apply_for_feature(feature_id=...)` skips other features' sub_bids.

    Important #3: when a sub_bid exists in two features, the
    feature-scoped apply must not pick up the other feature's entry.
    """
    from mage.orchestration.cosmetic_apply import apply_for_feature

    project_dir = tmp_path
    (project_dir / "mapping.yaml").write_text(
        yaml.safe_dump(
            MappingArtifact(
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
            ).model_dump(mode="json", by_alias=True),
            sort_keys=False,
        )
    )

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

    from mage.agents import cosmetic_refiner as cr_mod

    real_refiner = cr_mod.CosmeticRefiner
    cr_mod.CosmeticRefiner = _StubRefiner  # type: ignore[misc, assignment]
    try:
        rc = await apply_for_feature(
            project_dir,
            ["01JF"],
            dry_run=True,
            feature_id="feat-a",
        )
    finally:
        cr_mod.CosmeticRefiner = real_refiner
    assert rc == 0
    # Only feat-a's entry was processed
    assert captured == ["in-feat-a"]
