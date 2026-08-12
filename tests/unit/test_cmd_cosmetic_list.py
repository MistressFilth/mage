"""`mage cosmetic list` tests."""

from __future__ import annotations

import json
import subprocess
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


async def _write_mapping(
    project_dir: Path, *, feature_id: str, findings: list[dict]
) -> Path:
    """Write a mapping.yaml AND seed it onto the orphan branch (P32).

    The CLI reads through the state store, so the canonical seed must
    land on the orphan branch. The working-tree file is also kept for
    parity with the pre-migration layout; tests that still inspect it
    can read either copy.
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
    # P32: seed the orphan branch. init git first if not already.

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
        format: str = "text",
        filter: list[str] | None = None,
    ) -> None:
        self.feature_id = feature_id
        self.project_dir = project_dir
        self.format = format
        self.filter = filter


@pytest.mark.asyncio
async def test_list_text_renders_rows_sorted_by_sub_bid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": "01JG",
                "scenario_name": "logout",
                "location": "src/logout.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
            {
                "sub_bid": "01JF",
                "scenario_name": "signin",
                "location": "src/auth.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
        ],
    )
    rc = await cli.cmd_cosmetic_list(_Args(feature_id="feat", project_dir=tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    jf = out.index("01JF")
    jg = out.index("01JG")
    assert jf < jg


@pytest.mark.asyncio
async def test_list_json_stable_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await _write_mapping(
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
    rc = await cli.cmd_cosmetic_list(
        _Args(feature_id="feat", project_dir=tmp_path, format="json")
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload.keys()) == ["entries"]
    entry = payload["entries"][0]
    # `applied_at` is intentionally absent: the state model does not
    # store a timestamp, so promising a column we always render as
    # null would mislead readers (Minor #1).
    assert list(entry.keys()) == [
        "feature_id",
        "status",
        "sub_bid",
        "scenario",
        "file",
    ]


@pytest.mark.asyncio
async def test_list_applied_status_no_applied_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An applied entry surfaces `status=applied` and the file path.

    Minor #1: `applied_at` is no longer in the output schema; this
    test replaces the prior iso8601-applied_at test.
    """
    await _write_mapping(
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
    await save_state(
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
    rc = await cli.cmd_cosmetic_list(
        _Args(feature_id="feat", project_dir=tmp_path, format="json")
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["status"] == "applied"
    assert "applied_at" not in entry
    assert entry["file"] == "src/auth.py"


@pytest.mark.asyncio
async def test_list_filter_narrows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
                "text": "x",
                "proposed_by": "increment_quality",
            },
        ],
    )
    rc = await cli.cmd_cosmetic_list(
        _Args(
            feature_id="feat",
            project_dir=tmp_path,
            filter=["sub_bid=01JF"],
        )
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "01JF" in out
    assert "01JG" not in out


@pytest.mark.asyncio
async def test_list_filter_unknown_exits_2(
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
    rc = await cli.cmd_cosmetic_list(
        _Args(
            feature_id="feat",
            project_dir=tmp_path,
            filter=["sub_bid=01ZZ"],
        )
    )
    assert rc == 2


@pytest.mark.asyncio
async def test_list_empty_returns_empty_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await _write_mapping(tmp_path, feature_id="feat", findings=[])
    rc = await cli.cmd_cosmetic_list(
        _Args(feature_id="feat", project_dir=tmp_path, format="json")
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"entries": []}


@pytest.mark.asyncio
async def test_list_skips_entries_with_missing_sub_bid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Entries missing `sub_bid` must not crash `list` (Crit. 1).

    A queue entry without `sub_bid` is rendered as a row with empty
    `sub_bid`/file; the list call must not raise KeyError.
    """
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
            },
            {
                # no `sub_bid` key at all
                "scenario_name": "orphan",
                "location": "src/z.py",
                "text": "x",
                "proposed_by": "increment_quality",
            },
        ],
    )
    rc = await cli.cmd_cosmetic_list(
        _Args(feature_id="feat", project_dir=tmp_path, format="json")
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    sub_bids = [entry["sub_bid"] for entry in payload["entries"]]
    assert "01JF" in sub_bids
    assert "" in sub_bids


@pytest.mark.asyncio
async def test_list_skips_entries_with_explicit_null_sub_bid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Entries with `sub_bid: None` must not crash `list` (Crit. 2).

    The null entry is rendered as a row with empty sub_bid; the apply
    set must filter it out so apply does not crash on a None.
    """
    await _write_mapping(
        tmp_path,
        feature_id="feat",
        findings=[
            {
                "sub_bid": None,
                "scenario_name": "null-bid",
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
    rc = await cli.cmd_cosmetic_list(
        _Args(feature_id="feat", project_dir=tmp_path, format="json")
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    sub_bids = [entry["sub_bid"] for entry in payload["entries"]]
    assert sub_bids == ["", "01JF"] or sorted(sub_bids) == ["", "01JF"]
    # No None in serialized output
    assert None not in sub_bids
