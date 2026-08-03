"""End-to-end `mage cosmetic list` invocation."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from mage.artifacts.mapping import MappingArtifact


def _mage() -> list[str]:
    """Return the command list to invoke the `mage` console script."""
    binary = shutil.which("mage")
    if binary is None:
        pytest.fail("mage console script not found on PATH")
    return [binary]


def _write_mapping(path: Path, artifact: MappingArtifact) -> None:
    path.write_text(
        yaml.safe_dump(artifact.model_dump(mode="json", by_alias=True), sort_keys=False)
    )


def test_list_with_filter(tmp_path: Path) -> None:
    artifact = MappingArtifact(
        project_id="demo",
        cosmetic_findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "s1",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
                "feature_id": "feat-a",
            },
            {
                "sub_bid": "01JG",
                "scenario_name": "s2",
                "location": "src/b.py",
                "text": "y",
                "proposed_by": "increment_quality",
                "feature_id": "feat-a",
            },
            {
                "sub_bid": "01ZZ",
                "scenario_name": "s3",
                "location": "src/c.py",
                "text": "z",
                "proposed_by": "increment_quality",
                "feature_id": "feat-b",
            },
        ],
    )
    _write_mapping(tmp_path / "mapping.yaml", artifact)

    result = subprocess.run(
        [
            *_mage(),
            "cosmetic",
            "list",
            "feat-a",
            "--project-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert [entry["sub_bid"] for entry in payload["entries"]] == ["01JF", "01JG"]


def test_list_filter_unknown_sub_bid(tmp_path: Path) -> None:
    artifact = MappingArtifact(
        project_id="demo",
        cosmetic_findings=[
            {
                "sub_bid": "01JF",
                "scenario_name": "s",
                "location": "src/a.py",
                "text": "x",
                "proposed_by": "increment_quality",
                "feature_id": "feat-a",
            }
        ],
    )
    _write_mapping(tmp_path / "mapping.yaml", artifact)

    result = subprocess.run(
        [
            *_mage(),
            "cosmetic",
            "list",
            "feat-a",
            "--project-dir",
            str(tmp_path),
            "--filter",
            "sub_bid=01ZZ",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unknown sub_bid" in result.stderr
