"""`mage cosmetic show --raw` tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from mage import cli
from mage.artifacts.cosmetic_state import (
    CosmeticApplied,
    CosmeticAppliedState,
    save_state,
)
from mage.artifacts.mapping import MappingArtifact


def _write_mapping(
    project_dir: Path,
    *,
    feature_id: str,
    findings: list[dict],
    inspect_journal: dict[str, list[dict]] | None = None,
) -> Path:
    path = project_dir / "mapping.yaml"
    artifact = MappingArtifact(
        project_id="demo",
        cosmetic_findings=[{**f, "feature_id": feature_id} for f in findings],
        inspect_journal=inspect_journal or {},
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
        raw: bool = False,
        journal: bool = False,
        filter: list[str] | None = None,
    ) -> None:
        self.feature_id = feature_id
        self.project_dir = project_dir
        self.raw = raw
        self.journal = journal
        self.filter = filter


def test_show_raw_dumps_one_block_per_finding_sorted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JG",
                "scenario_name": "logout",
                "location": "src/logout.py",
                "text": "trim",
                "proposed_by": "increment_quality",
            },
            {
                "sub_bid": "01JF",
                "scenario_name": "signin",
                "location": "src/auth.py",
                "text": "tighten",
                "proposed_by": "increment_quality",
            },
        ],
    )
    rc = asyncio.run(
        cli.cmd_cosmetic_show(_Args(feature_id="feat", project_dir=tmp_path, raw=True))
    )
    assert rc == 0
    out = capsys.readouterr().out
    jf_idx = out.index("01JF")
    jg_idx = out.index("01JG")
    assert jf_idx < jg_idx  # ascending sort


def test_show_raw_reports_pending_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "signin",
                "location": "src/auth.py",
                "text": "...",
                "proposed_by": "increment_quality",
            }
        ],
    )
    rc = asyncio.run(
        cli.cmd_cosmetic_show(_Args(feature_id="feat", project_dir=tmp_path, raw=True))
    )
    assert rc == 0
    assert "status: pending" in capsys.readouterr().out


def test_show_raw_reports_applied_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "signin",
                "location": "src/auth.py",
                "text": "...",
                "proposed_by": "increment_quality",
            }
        ],
    )
    asyncio.run(
        save_state(
            tmp_path,
            CosmeticAppliedState(
                applied={
                    "01JF": CosmeticApplied(
                        content_hash="x" * 64,
                        file=tmp_path / "src/auth.py",
                        rationale="applied",
                    )
                }
            ),
        )
    )
    rc = asyncio.run(
        cli.cmd_cosmetic_show(_Args(feature_id="feat", project_dir=tmp_path, raw=True))
    )
    assert rc == 0
    assert "status: applied" in capsys.readouterr().out


def test_show_raw_empty_queue_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_mapping(tmp_path, feature_id="feat", findings=[])
    rc = asyncio.run(
        cli.cmd_cosmetic_show(_Args(feature_id="feat", project_dir=tmp_path, raw=True))
    )
    assert rc == 0


def test_show_raw_filter_unknown_sub_bid_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "signin",
                "location": "src/auth.py",
                "text": "x",
                "proposed_by": "increment_quality",
            }
        ],
    )
    rc = asyncio.run(
        cli.cmd_cosmetic_show(
            _Args(
                feature_id="feat",
                project_dir=tmp_path,
                raw=True,
                filter=["sub_bid=01ZZ"],
            )
        )
    )
    assert rc == 2
    assert "unknown sub_bid" in capsys.readouterr().err
