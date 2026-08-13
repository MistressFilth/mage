"""Tests for the CLI entry point."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mage import cli


class _PassthroughRefiner:
    """Refines raw queue dicts into CosmeticPatch objects verbatim."""

    async def refine(self, raw, *, semaphore):
        from pathlib import Path as _P

        from mage.artifacts.cosmetic import CosmeticPatch

        return CosmeticPatch(
            sub_bid=raw["sub_bid"],
            file_path=_P(raw["location"]["file"]),
            line_range=(raw["location"]["line"] - 1, raw["location"]["line"] + 1),
            replacement_text="x = 42\n",
            rationale=raw["text"],
            proposed_by=raw["proposed_by"],
        )


class TestCli:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--help"])
        assert exc_info.value.code == 0

    def test_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main([])
        assert exc_info.value.code in (0, 1, 2)

    @pytest.mark.asyncio
    async def test_verify_subcommand_runs_mechanical_checks(
        self, tmp_project_dir: Path
    ):
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: Valid\n    Given x\n    When y\n    Then z\n"
        )
        # cmd_verify calls state_store_for, which (Fix 1) auto-migrates
        # any legacy ``.mage/`` into the orphan branch. Init git so the
        # orphan branch has somewhere to land; this test is not about
        # the migration path.
        from tests.conftest import init_git_repo

        init_git_repo(tmp_project_dir)

        from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact

        mapping = MappingArtifact(
            schema_version=2,
            project_id="cli-test",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b",
                    behavior_description="d",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                    behavior_halt=[],
                )
            ],
        )
        await mapping.save(tmp_project_dir / "mapping.yaml")

        rc = _run_cli(
            "--project-dir",
            str(tmp_project_dir),
            "verify",
            "--feature",
            str(feature_path),
            "--scenario",
            "Valid",
            "--sub-bid",
            "A",
            "--base-bid",
            "00000",
        )
        assert rc in (0, 1)


def _run_cli(*args, **kwargs):
    """Execute the CLI's `main` coroutine on a fresh event loop.

    The CLI uses `asyncio.run` internally, which fails when called
    from within a running event loop. This helper runs the CLI on a
    fresh event loop in a separate thread, where no outer loop is
    running.
    """
    import threading

    from mage.cli import main

    result_box: list = []
    error_box: list = []

    def _target():
        try:
            result_box.append(main(*args))
        except BaseException as exc:  # noqa: BLE001 — thread target must catch everything to surface the result
            error_box.append(exc)

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if error_box:
        raise error_box[0]
    return result_box[0] if result_box else None


def _state_store_for(project_dir: Path):
    """Build a StateStore anchored at ``project_dir`` (P32 task 13)."""
    from mage.state_store import StateStore

    return StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))


async def _seed_state_store_mapping(project_dir: Path) -> None:
    """Init a git repo at ``project_dir`` and write ``mapping.yaml`` to the
    orphan-branch state store (P32).

    Most CLI tests seed a working-tree ``mapping.yaml`` directly. The new
    CLI reads through the state store, so the seed must land on the orphan
    branch instead. The on-disk ``mapping.yaml`` may still exist (some
    tests inspect it) but the canonical data lives at the state-store path.
    """
    import asyncio
    import subprocess

    from mage.state_store import StateStore

    def _run_git(args: list[str]) -> None:
        subprocess.run(args, cwd=project_dir, check=True, capture_output=True)

    await asyncio.to_thread(_run_git, ["git", "init"])
    await asyncio.to_thread(_run_git, ["git", "config", "user.name", "T"])
    await asyncio.to_thread(_run_git, ["git", "config", "user.email", "t@e"])
    state_store = StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))
    mapping_path = project_dir / "mapping.yaml"
    if mapping_path.exists():
        import yaml

        from mage.artifacts.mapping import MappingArtifact

        mapping = MappingArtifact.model_validate(
            yaml.safe_load(mapping_path.read_text())
        )
        await mapping.save_to_state_store(state_store)


@pytest.mark.asyncio
async def test_plan_show_prints_digest_and_content(tmp_path, capsys):
    import sys

    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    await PlanArtifact.finalize(plan_path, "# Plan\n\ncontent\n", log)

    test_argv = ["mage", "--project-dir", str(tmp_path), "plan", "show"]
    with patch.object(sys, "argv", test_argv):
        _run_cli()

    captured = capsys.readouterr()
    assert "Plan:" in captured.out
    assert str(plan_path) in captured.out
    assert "Digest:" in captured.out
    assert "# Plan" in captured.out


@pytest.mark.asyncio
async def test_plan_revise_records_event(tmp_path, capsys):
    import sys

    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog, EventType

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    await PlanArtifact.finalize(plan_path, "# original\n", log)
    plan_path.write_text("# revised\n", encoding="utf-8")

    test_argv = [
        "mage",
        "--project-dir",
        str(tmp_path),
        "plan",
        "revise",
        "--reason",
        "Reordered behaviors",
        "--approver",
        "alice",
    ]
    with patch.object(sys, "argv", test_argv):
        _run_cli()

    revised = [e for e in log.read_all() if e.event_type == EventType.PLAN_REVISED]
    assert len(revised) == 1
    assert revised[0].payload["reason"] == "Reordered behaviors"
    assert revised[0].payload["human_approver"] == "alice"

    captured = capsys.readouterr()
    assert (
        "Plan revision recorded" in captured.out or "revision" in captured.out.lower()
    )


@pytest.mark.asyncio
async def test_plan_revise_warns_on_unchanged_digest(tmp_path, capsys):
    import sys

    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    await PlanArtifact.finalize(plan_path, "# same\n", log)

    test_argv = [
        "mage",
        "--project-dir",
        str(tmp_path),
        "plan",
        "revise",
        "--reason",
        "r",
        "--approver",
        "a",
    ]
    with patch.object(sys, "argv", test_argv):
        _run_cli()

    captured = capsys.readouterr()
    assert "Plan digest unchanged; recording anyway" in captured.err


def test_plan_revise_missing_plan(tmp_path, capsys):
    import sys

    test_argv = [
        "mage",
        "--project-dir",
        str(tmp_path),
        "plan",
        "revise",
        "--reason",
        "r",
        "--approver",
        "a",
    ]
    with patch.object(sys, "argv", test_argv), pytest.raises(SystemExit) as exc_info:
        _run_cli()
    assert exc_info.value.code != 0


def test_mage_run_without_dry_run_does_not_raise_not_implemented(tmp_path):
    """`mage run` without --dry-run used to raise NotImplementedError (Plan 9 gate).

    Plan 9 unlocks the path: agent wiring is driven by host_config.model, so
    real-agent or stub-agent paths both run end-to-end. We only assert the
    gate is gone — other failures (missing project files) are acceptable.
    """
    from mage.cli import _main

    test_argv = ["mage", "--project-dir", str(tmp_path), "run"]
    try:
        import asyncio as _aio

        _aio.run(_main(test_argv))
    except SystemExit:
        pass  # argparse exit codes from missing args are fine
    except NotImplementedError as exc:
        pytest.fail(
            f"cmd_run still raises NotImplementedError after Plan 9 unlock: {exc}"
        )
    except (OSError, ValueError, RuntimeError, KeyError):
        pass  # other failures are OK; we only check the gate is gone


def test_mage_run_dry_run_completes_on_empty_project(tmp_path):
    """Empty project: no behaviors, no approved scenarios. Pipeline should
    no-op cleanly and exit 0."""
    import subprocess as _sp

    from mage.cli import main

    project = tmp_path / "proj"
    project.mkdir()
    # P32: mapping lives on the orphan branch; init a git repo and seed it.
    _sp.run(["git", "init"], cwd=project, check=True, capture_output=True)
    _sp.run(
        ["git", "config", "user.name", "T"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "config", "user.email", "t@e"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    rc = main(["run", "--dry-run", "--project-dir", str(project)])
    assert rc == 0


def test_mage_run_dry_run_does_not_raise_systemexit(tmp_path):
    """Empty project does not emit a halt; mage run returns 0, not SystemExit."""
    import subprocess as _sp

    from mage.cli import main

    project = tmp_path / "proj"
    project.mkdir()
    # P32: mapping lives on the orphan branch; init a git repo.
    _sp.run(["git", "init"], cwd=project, check=True, capture_output=True)
    _sp.run(
        ["git", "config", "user.name", "T"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "config", "user.email", "t@e"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    # The halt scenario is covered in Task 14. This test pins the
    # no-op contract: empty project with --dry-run returns cleanly.
    rc = main(["run", "--dry-run", "--project-dir", str(project)])
    assert rc == 0


@pytest.mark.asyncio
async def test_review_show_prints_latest_aggregate(tmp_path, capsys):
    import asyncio
    import subprocess
    import sys
    from datetime import UTC, datetime

    from mage.artifacts.verdict import (
        DimensionSummary,
        ReviewerAggregate,
        VerdictArtifact,
    )
    from mage.orchestration.events import EventsLog
    from mage.state_store import StateStore

    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    def _run_git(args: list[str]) -> None:
        subprocess.run(args, cwd=project_dir, check=True, capture_output=True)

    await asyncio.to_thread(_run_git, ["git", "init"])
    await asyncio.to_thread(_run_git, ["git", "config", "user.name", "T"])
    await asyncio.to_thread(_run_git, ["git", "config", "user.email", "t@e"])
    state_store = StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))
    log = EventsLog(project_dir / "events.jsonl")

    agg = ReviewerAggregate(
        draft_hash="x",
        aggregated_at=datetime.now(UTC),
        iteration=1,
        per_dimension={
            "spec_compliance": DimensionSummary(
                outcome="pass",
                reviewer_verdict_ref="r.yaml",
                findings_count=0,
            ),
        },
        decision="approved",
        reasoning="all passed",
    )
    await VerdictArtifact.finalize_to_state_store(
        state_store, "verdicts/x/aggregate.yaml", agg, log
    )

    test_argv = ["mage", "--project-dir", str(project_dir), "review", "show"]
    with patch.object(sys, "argv", test_argv):
        rc = _run_cli()
    assert rc == 0

    captured = capsys.readouterr()
    assert "approved" in captured.out


def test_mage_review_resume_is_gone(tmp_path, capsys):
    from mage.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["review", "resume", "--project-dir", str(tmp_path)])
    assert exc.value.code == 2


class TestCosmeticShow:
    @pytest.mark.asyncio
    async def test_cosmetic_show_refines_and_prints_items(
        self, tmp_path, capsys, monkeypatch
    ):
        from pathlib import Path

        import yaml

        from mage.artifacts.cosmetic import CosmeticPatch

        project_dir = tmp_path
        mapping_path = project_dir / "mapping.yaml"
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(
            yaml.safe_dump(
                {
                    "project_id": "p",
                    "base_bids": [],
                    "feature_cosmetic_queue": [
                        {
                            "feature_id": "feat-1",
                            "sub_bid": "00000-001",
                            "text": "use a constant",
                            "location": {"file": "src/example.py", "line": 5},
                            "proposed_by": "IncrementQualityReviewer",
                        }
                    ],
                }
            )
        )
        await _seed_state_store_mapping(project_dir)

        stub_item = CosmeticPatch(
            sub_bid="00000-001",
            file_path=Path("src/example.py"),
            line_range=(4, 6),
            replacement_text="CONST = 42\n",
            rationale="use a constant",
            proposed_by="IncrementQualityReviewer",
        )

        class StubRefiner:
            async def refine(self, raw, *, semaphore):
                return stub_item

        monkeypatch.setattr(
            "mage.agents.cosmetic_refiner.CosmeticRefiner",
            lambda **kw: StubRefiner(),
        )

        rc = _run_cli(
            "cosmetic",
            "show",
            "feat-1",
            "--project-dir",
            str(project_dir),
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "src/example.py" in captured.out
        assert "00000-001" in captured.out

    @pytest.mark.asyncio
    async def test_cosmetic_show_filters_by_feature_id(
        self, tmp_path, capsys, monkeypatch
    ):
        import yaml

        project_dir = tmp_path
        mapping_path = project_dir / "mapping.yaml"
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "project_id": "p",
                    "base_bids": [],
                    "feature_cosmetic_queue": [
                        {
                            "feature_id": "feat-1",
                            "sub_bid": "00000-001",
                            "text": "match",
                            "location": {"file": "src/match.py", "line": 5},
                            "proposed_by": "IncrementQualityReviewer",
                        },
                        {
                            "feature_id": "feat-2",
                            "sub_bid": "00000-002",
                            "text": "other",
                            "location": {"file": "src/other.py", "line": 7},
                            "proposed_by": "IncrementQualityReviewer",
                        },
                    ],
                }
            )
        )
        await _seed_state_store_mapping(project_dir)

        monkeypatch.setattr(
            "mage.agents.cosmetic_refiner.CosmeticRefiner",
            lambda **kw: _PassthroughRefiner(),
        )

        rc = _run_cli(
            "cosmetic",
            "show",
            "feat-1",
            "--project-dir",
            str(project_dir),
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "src/match.py" in captured.out
        assert "src/other.py" not in captured.out
        assert "00000-001" in captured.out
        assert "00000-002" not in captured.out


class TestCosmeticApply:
    @pytest.mark.asyncio
    async def test_cosmetic_apply_dry_run_does_not_write_or_commit(
        self, tmp_path, capsys, monkeypatch
    ):
        """--dry-run refines + emits events, but does not touch files or run git."""
        from pathlib import Path

        import yaml

        from mage.artifacts.cosmetic import CosmeticPatch

        project_dir = tmp_path
        target_file = project_dir / "src" / "example.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        (project_dir / "mapping.yaml").write_text(
            yaml.safe_dump(
                {
                    "project_id": "p",
                    "base_bids": [],
                    "feature_cosmetic_queue": [
                        {
                            "feature_id": "feat-1",
                            "sub_bid": "00000-001",
                            "text": "use a constant",
                            "location": {"file": "src/example.py", "line": 3},
                            "proposed_by": "IncrementQualityReviewer",
                        }
                    ],
                }
            )
        )
        await _seed_state_store_mapping(project_dir)

        stub_item = CosmeticPatch(
            sub_bid="00000-001",
            file_path=Path("src/example.py"),
            line_range=(3, 3),
            replacement_text="CONST = 42\n",
            rationale="use a constant",
            proposed_by="IncrementQualityReviewer",
        )

        class StubRefiner:
            async def refine(self, raw, *, semaphore):
                return stub_item

        monkeypatch.setattr(
            "mage.agents.cosmetic_refiner.CosmeticRefiner",
            lambda **kw: StubRefiner(),
        )

        # Stub subprocess so we can detect whether git commit was attempted.
        recorded: list[tuple] = []

        # The mapping.yaml content the CLI should read back via the state store.
        mapping_text = (project_dir / "mapping.yaml").read_text()

        def fake_run(cmd, **kwargs):
            recorded.append((cmd, kwargs))

            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            r.stdout = ""
            # Return the seeded mapping when the CLI's state store reads
            # it back via `git show refs/mage/...:mapping.yaml`.
            if cmd[:2] == ["git", "show"] and "refs/mage/" in cmd[2]:
                r.stdout = mapping_text
            return r

        monkeypatch.setattr("subprocess.run", fake_run)
        rc = _run_cli(
            "cosmetic",
            "apply",
            "feat-1",
            "--dry-run",
            "--project-dir",
            str(project_dir),
        )
        assert rc == 0
        assert "CONST = 42" not in target_file.read_text(), (
            "dry-run must not modify the file"
        )
        # Filter out the state-store read/show calls — they're internal
        # state-store plumbing, not user-visible commits. The state store
        # also shells `git config user.name/email` to resolve identity.
        user_git_calls = [
            (cmd, kwargs)
            for cmd, kwargs in recorded
            if not (
                (cmd[:2] == ["git", "show"] and "refs/mage/" in cmd[2])
                or (
                    cmd[:2] == ["git", "config"]
                    and cmd[2] in ("user.name", "user.email")
                )
            )
        ]
        assert user_git_calls == [], (
            f"dry-run must not invoke git, got {user_git_calls!r}"
        )
        # Event was logged though.
        events = list((project_dir / "events.jsonl").read_text().splitlines())
        assert any("cosmetic_item_skipped" in line for line in events), (
            f"dry-run must emit COSMETIC_ITEM_SKIPPED, got: {events!r}"
        )
        assert all("cosmetic_item_applied" not in line for line in events), (
            "dry-run must not emit COSMETIC_ITEM_APPLIED"
        )
        assert all("cosmetic_refiner_fallback" not in line for line in events)

    @pytest.mark.asyncio
    async def test_cosmetic_apply_filters_by_feature_id(self, tmp_path, monkeypatch):
        import yaml

        project_dir = tmp_path
        target_match = project_dir / "src" / "match.py"
        target_match.parent.mkdir(parents=True, exist_ok=True)
        target_match.write_text("line1\nline2\nline3\nline4\nline5\n")
        target_other = project_dir / "src" / "other.py"
        target_other.write_text("line1\nline2\nline3\nline4\nline5\n")

        (project_dir / "mapping.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "project_id": "p",
                    "base_bids": [],
                    "feature_cosmetic_queue": [
                        {
                            "feature_id": "feat-1",
                            "sub_bid": "00000-001",
                            "text": "match",
                            "location": {"file": "src/match.py", "line": 3},
                            "proposed_by": "IncrementQualityReviewer",
                        },
                        {
                            "feature_id": "feat-2",
                            "sub_bid": "00000-002",
                            "text": "other",
                            "location": {"file": "src/other.py", "line": 3},
                            "proposed_by": "IncrementQualityReviewer",
                        },
                    ],
                }
            )
        )

        monkeypatch.setattr(
            "mage.agents.cosmetic_refiner.CosmeticRefiner",
            lambda **kw: _PassthroughRefiner(),
        )

        # P32: seed the mapping on the orphan branch so the CLI can read it.
        await _seed_state_store_mapping(project_dir)

        # Stub subprocess so we don't try to git-commit.
        recorded: list[tuple] = []

        mapping_text = (project_dir / "mapping.yaml").read_text()

        def fake_run(cmd, **kwargs):
            recorded.append((cmd, kwargs))

            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            r.stdout = ""
            if cmd[:2] == ["git", "show"] and "refs/mage/" in cmd[2]:
                r.stdout = mapping_text
            return r

        monkeypatch.setattr("subprocess.run", fake_run)
        rc = _run_cli(
            "cosmetic",
            "apply",
            "feat-1",
            "--dry-run",
            "--project-dir",
            str(project_dir),
        )
        assert rc == 0
        # Filter narrows event log to the matching feature only.
        events = list((project_dir / "events.jsonl").read_text().splitlines())
        assert any("src/match.py" in line for line in events), (
            f"feat-1 item must be in event log, got: {events!r}"
        )
        assert not any("src/other.py" in line for line in events), (
            f"feat-2 item must not be applied when filtering for feat-1; got: {events!r}"
        )

    @pytest.mark.asyncio
    async def test_cosmetic_apply_skips_already_applied_with_matching_hash(
        self, tmp_path, monkeypatch
    ):
        """When state file records prior apply with matching hash, emit SKIPPED."""
        from pathlib import Path

        import yaml

        from mage.artifacts.cosmetic import CosmeticPatch
        from mage.artifacts.cosmetic_state import (
            CosmeticApplied,
            CosmeticAppliedState,
            save_state_via_store,
        )

        project_dir = tmp_path
        target = project_dir / "src" / "example.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line1\nline2\nline3\n")

        (project_dir / "mapping.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "project_id": "p",
                    "base_bids": [],
                    "feature_cosmetic_queue": [
                        {
                            "feature_id": "feat-1",
                            "sub_bid": "00000-001",
                            "text": "use a constant",
                            "location": {"file": "src/example.py", "line": 2},
                            "proposed_by": "IncrementQualityReviewer",
                        }
                    ],
                }
            )
        )

        # Use the same replacement_text `_PassthroughRefiner` produces so the
        # computed hash matches what the SUT will see.
        item = CosmeticPatch(
            sub_bid="00000-001",
            file_path=Path("src/example.py"),
            line_range=(2, 2),
            replacement_text="x = 42\n",
            rationale="use a constant",
            proposed_by="IncrementQualityReviewer",
        )

        # P32: seed the mapping on the orphan branch so the CLI can read it.
        await _seed_state_store_mapping(project_dir)

        # Pre-seed state with matching hash.
        prior = CosmeticAppliedState(
            applied={
                "00000-001": CosmeticApplied(
                    content_hash=item.content_hash,
                    file=Path("src/example.py"),
                    rationale="use a constant",
                ),
            }
        )
        await save_state_via_store(_state_store_for(project_dir), prior)

        monkeypatch.setattr(
            "mage.agents.cosmetic_refiner.CosmeticRefiner",
            lambda **kw: _PassthroughRefiner(),
        )

        rc = _run_cli("cosmetic", "apply", "feat-1", "--project-dir", str(project_dir))
        assert rc == 0
        # File NOT edited (already-applied).
        assert "x = 42" not in target.read_text()
        events = list((project_dir / "events.jsonl").read_text().splitlines())
        assert any("cosmetic_item_skipped" in line for line in events)

    @pytest.mark.asyncio
    async def test_cosmetic_apply_reapplies_when_hash_differs(
        self, tmp_path, monkeypatch
    ):
        """State record with DIFFERENT hash → fresh apply (replaces content)."""
        from pathlib import Path

        import yaml

        from mage.artifacts.cosmetic_state import (
            CosmeticApplied,
            CosmeticAppliedState,
            save_state_via_store,
        )

        project_dir = tmp_path
        target = project_dir / "src" / "example.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line1\nline2\nline3\n")

        (project_dir / "mapping.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "project_id": "p",
                    "base_bids": [],
                    "feature_cosmetic_queue": [
                        {
                            "feature_id": "feat-1",
                            "sub_bid": "00000-001",
                            "text": "use a constant",
                            "location": {"file": "src/example.py", "line": 2},
                            "proposed_by": "IncrementQualityReviewer",
                        }
                    ],
                }
            )
        )

        # P32: seed the mapping on the orphan branch so the CLI can read it.
        await _seed_state_store_mapping(project_dir)

        prior = CosmeticAppliedState(
            applied={
                "00000-001": CosmeticApplied(
                    content_hash="different-hash-9999",
                    file=Path("src/example.py"),
                    rationale="prior content",
                ),
            }
        )
        await save_state_via_store(_state_store_for(project_dir), prior)

        monkeypatch.setattr(
            "mage.agents.cosmetic_refiner.CosmeticRefiner",
            lambda **kw: _PassthroughRefiner(),
        )

        recorded: list[tuple] = []

        mapping_text = (project_dir / "mapping.yaml").read_text()

        def fake_run(cmd, **kwargs):
            recorded.append((cmd, kwargs))

            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            r.stdout = ""
            if cmd[:2] == ["git", "show"] and "refs/mage/" in cmd[2]:
                r.stdout = mapping_text
            return r

        # Patch subprocess.run directly: the asyncio.to_thread wrapper in
        # cli.py preserves the patched function without blocking the LLM
        # refine fan-out (which also goes through asyncio.to_thread).
        monkeypatch.setattr("subprocess.run", fake_run)

        rc = _run_cli("cosmetic", "apply", "feat-1", "--project-dir", str(project_dir))
        assert rc == 0
        assert "x = 42" in target.read_text(), "hash mismatch must allow reapply"

        # Filter out state-store plumbing — read/write on the mage orphan
        # branch (refs/mage/...) does not count as a user-visible commit.
        # Only the cosmetic-apply "git commit" of the file change should
        # remain. The state-store's plumbing subcommands and its identity-
        # resolution config probes are filtered out.
        def _is_state_store_plumbing(cmd: list[str]) -> bool:
            sub = cmd[:2] if len(cmd) >= 2 else [""]
            if sub[0] != "git":
                return False
            plumbing_subcommands = {
                "mktree",
                "hash-object",
                "commit-tree",
                "update-ref",
                "ls-tree",
                "show",
                "rev-parse",
            }
            if sub[1] in plumbing_subcommands:
                return True
            config_probes = {"user.name", "user.email"}
            return bool(
                sub[1] == "config" and len(cmd) >= 3 and cmd[2] in config_probes
            )

        user_git_calls = [
            (cmd, kwargs)
            for cmd, kwargs in recorded
            if not _is_state_store_plumbing(cmd)
        ]
        assert len(user_git_calls) == 1, (
            f"expected exactly one git commit invocation, got {user_git_calls!r}"
        )


class TestInspectShow:
    @pytest.mark.asyncio
    async def test_inspect_show_renders_artifact(self, tmp_path, capsys):
        import asyncio
        import subprocess
        from datetime import UTC, datetime

        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.orchestration.events import EventsLog
        from mage.state_store import StateStore

        # Build a minimal project with an InspectArtifact on the orphan branch.
        project = tmp_path / "proj"
        project.mkdir()

        def _run_git(args: list[str]) -> None:
            subprocess.run(args, cwd=project, check=True, capture_output=True)

        await asyncio.to_thread(_run_git, ["git", "init"])
        await asyncio.to_thread(_run_git, ["git", "config", "user.name", "T"])
        await asyncio.to_thread(_run_git, ["git", "config", "user.email", "t@e"])
        state_store = StateStore(project, "feature-artifacts", identity=("T", "t@e"))
        log = EventsLog(project / "events.jsonl")
        artifact = InspectArtifactContent(
            feature_id="feat-1",
            inspected_at=datetime.now(UTC),
            iteration=1,
            eof_max_iterations=3,
            scenarios=[],
            per_reviewer=[],
            critical=[],
            important=[],
            minor=[],
            cross_scenario=[],
            ready_to_merge=True,
            ledger_markdown="| step | result |\n|---|---|\n| mechanical | pass |",
        )
        await InspectArtifact.finalize_to_state_store(
            state_store, "inspect/feat-1/1.yaml", artifact, log
        )

        rc = _run_cli(["inspect", "show", "feat-1", "--project-dir", str(project)])
        out = capsys.readouterr().out
        assert "feat-1" in out
        assert "ready_to_merge" in out or "Ready" in out
        assert rc == 0


class TestSettleRun:
    @staticmethod
    def _install_runner(monkeypatch, project, *, test_returncode=0):
        from subprocess import CompletedProcess

        def runner(command, *, cwd):
            outputs = {
                ("git", "rev-parse", "--git-dir"): str(project / ".git"),
                ("git", "rev-parse", "--git-common-dir"): str(project / ".git"),
                ("git", "rev-parse", "--show-toplevel"): str(project),
                ("git", "branch", "--show-current"): "feature/settle",
            }
            returncode = (
                test_returncode if command == ["uv", "run", "pytest", "-v"] else 0
            )
            return CompletedProcess(
                command,
                returncode,
                stdout=outputs.get(tuple(command), "") + "\n",
                stderr="tests failed" if returncode else "",
            )

        monkeypatch.setattr(
            "mage.orchestration.settle_feature._default_command_runner",
            runner,
        )

    @pytest.mark.asyncio
    async def test_settle_run_non_interactive(self, tmp_path, capsys, monkeypatch):
        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.orchestration.events import EventsLog
        from mage.state_store import StateStore

        project = tmp_path / "proj"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        self._install_runner(monkeypatch, project)

        # P32: init a git repo so the state store has somewhere to live.
        # The mapping is empty here; load_from_state_store tolerates that.
        import asyncio
        import subprocess

        def _run_git(args: list[str]) -> None:
            subprocess.run(args, cwd=project, check=True, capture_output=True)

        await asyncio.to_thread(_run_git, ["git", "init"])
        await asyncio.to_thread(_run_git, ["git", "config", "user.name", "T"])
        await asyncio.to_thread(_run_git, ["git", "config", "user.email", "t@e"])
        state_store = StateStore(project, "feature-artifacts", identity=("T", "t@e"))

        # Build a ready-to-merge InspectArtifact on the orphan branch.
        artifact = InspectArtifactContent(
            feature_id="feat-1",
            inspected_at=datetime.now(UTC),
            iteration=1,
            eof_max_iterations=3,
            scenarios=[],
            per_reviewer=[],
            critical=[],
            important=[],
            minor=[],
            cross_scenario=[],
            ready_to_merge=True,
            ledger_markdown="",
        )
        await InspectArtifact.finalize_to_state_store(
            state_store, "inspect/feat-1/1.yaml", artifact, log
        )

        rc = _run_cli(
            [
                "settle",
                "run",
                "feat-1",
                "--disposition",
                "kept",
                "--project-dir",
                str(project),
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "settle" in out.lower() or "feat-1" in out

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert "settle_feature_finalized" in types
        disposal_events = [
            e for e in events if e.event_type.value == "settle_feature_finalized"
        ]
        assert disposal_events[0].payload["disposition"] == "kept"

    @pytest.mark.asyncio
    async def test_settle_run_returns_nonzero_when_tests_fail(
        self,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        import asyncio
        import subprocess

        from mage.artifacts.inspect import InspectArtifact, InspectArtifactContent
        from mage.orchestration.events import EventsLog
        from mage.state_store import StateStore

        project = tmp_path / "proj"
        project.mkdir()
        log = EventsLog(project / "events.jsonl")
        self._install_runner(monkeypatch, project, test_returncode=1)

        def _run_git(args: list[str]) -> None:
            subprocess.run(args, cwd=project, check=True, capture_output=True)

        await asyncio.to_thread(_run_git, ["git", "init"])
        await asyncio.to_thread(_run_git, ["git", "config", "user.name", "T"])
        await asyncio.to_thread(_run_git, ["git", "config", "user.email", "t@e"])
        state_store = StateStore(project, "feature-artifacts", identity=("T", "t@e"))
        await InspectArtifact.finalize_to_state_store(
            state_store,
            "inspect/feat-1/1.yaml",
            InspectArtifactContent(
                feature_id="feat-1",
                inspected_at=datetime.now(UTC),
                iteration=1,
                eof_max_iterations=3,
                ready_to_merge=True,
            ),
            log,
        )

        rc = _run_cli(
            [
                "settle",
                "run",
                "feat-1",
                "--disposition",
                "kept",
                "--project-dir",
                str(project),
            ]
        )

        assert rc == 1
        assert "tests failed" in capsys.readouterr().err.lower()
        assert not any(
            event.event_type.value == "settle_feature_finalized"
            for event in log.read_all()
        )

    def test_settle_run_reports_value_errors_without_traceback(
        self,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        from mage.orchestration.settle_feature import SettleFeatureStage

        project = tmp_path / "proj"
        project.mkdir()

        def explode(self, context, *, feature_id, disposition):
            raise ValueError("mapping artifact is missing base_bids")

        monkeypatch.setattr(SettleFeatureStage, "run_settle", explode)

        rc = _run_cli(
            [
                "settle",
                "run",
                "feat-1",
                "--disposition",
                "kept",
                "--project-dir",
                str(project),
            ]
        )

        assert rc == 1
        assert "base_bids" in capsys.readouterr().err
