"""`mage cosmetic show --journal` tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from mage import cli
from mage.artifacts.mapping import MappingArtifact


def _mapping_with_journal(
    project_dir: Path,
    *,
    feature_id: str,
    journal_entries: list[dict],
) -> Path:
    by_sub: dict[str, list[dict]] = {}
    for entry in journal_entries:
        by_sub.setdefault(entry["sub_bid"], []).append(
            {**entry, "feature_id": feature_id}
        )
    path = project_dir / "mapping.yaml"
    artifact = MappingArtifact(project_id="demo", inspect_journal=by_sub)
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


def _entry(sub_bid: str, timestamp: datetime, finding_id: str) -> dict:
    return {
        "sub_bid": sub_bid,
        "timestamp": timestamp,
        "scenario_id": "s",
        "iteration": 1,
        "dimension": "mechanical",
        "severity": "minor",
        "route": "spec",
        "finding_id": finding_id,
        "location": "src/x.py:1",
        "issue": "i",
        "rationale": "r",
    }


def test_journal_section_filters_by_feature_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mapping_with_journal(
        tmp_path,
        feature_id="feat-a",
        journal_entries=[
            _entry("01JF", datetime(2026, 8, 1, tzinfo=UTC), "f1"),
            _entry("01JG", datetime(2026, 8, 2, tzinfo=UTC), "f2"),
        ],
    )
    rc = asyncio.run(
        cli.cmd_cosmetic_show(
            _Args(feature_id="feat-a", project_dir=tmp_path, raw=True, journal=True)
        )
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert (
        "## Inspect journal" in out and "f1" in out and "f2" in out and "f3" not in out
    )


def test_journal_section_sorted_descending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mapping_with_journal(
        tmp_path,
        feature_id="feat",
        journal_entries=[
            _entry("01JF", datetime(2026, 8, 1, tzinfo=UTC), "f-old"),
            _entry("01JG", datetime(2026, 8, 5, tzinfo=UTC), "f-new"),
        ],
    )
    asyncio.run(
        cli.cmd_cosmetic_show(
            _Args(feature_id="feat", project_dir=tmp_path, raw=True, journal=True)
        )
    )
    out = capsys.readouterr().out
    assert out.index("f-new") < out.index("f-old")


def test_journal_section_absent_when_no_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mapping_with_journal(tmp_path, feature_id="feat", journal_entries=[])
    rc = asyncio.run(
        cli.cmd_cosmetic_show(
            _Args(feature_id="feat", project_dir=tmp_path, raw=True, journal=True)
        )
    )
    assert rc == 0
    assert "## Inspect journal" not in capsys.readouterr().out


def test_journal_works_with_refined_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mapping_with_journal(
        tmp_path,
        feature_id="feat",
        journal_entries=[_entry("01JF", datetime(2026, 8, 1, tzinfo=UTC), "j1")],
    )
    rc = asyncio.run(
        cli.cmd_cosmetic_show(
            _Args(feature_id="feat", project_dir=tmp_path, journal=True)
        )
    )
    assert rc == 0
    assert "j1" in capsys.readouterr().out
