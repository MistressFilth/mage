"""E2E tests for `mage run --feature-id` (plan 22 task 3).

Smoke-tests that `mage run --feature-id` does not crash under --dry-run, and
verifies feature_id threads to persisted state on halt.
"""

from __future__ import annotations

import threading

import pytest
import yaml

from mage.cli import _make_dry_run_runner as _REAL_DRY_RUN_RUNNER
from mage.cli import main


def _setup_empty_project(project_dir):
    """Create a minimal project skeleton for mage run (smoke-test default)."""
    project_dir.mkdir(parents=True)
    (project_dir / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: e2e-run-feature-id-default\nbase_bids: []\n"
    )


async def _plant_feature_id_fixture(project_dir):
    """Plant a fixture with one APPROVED scenario, ready for halt injection."""
    project_dir.mkdir(parents=True, exist_ok=True)

    from mage.artifacts.mapping import (
        BaseBIDEntry,
        LifecycleStatus,
        MappingArtifact,
        ScenarioEntry,
    )

    mapping = MappingArtifact(
        schema_version=2,
        project_id=project_dir.name,
        base_bids=[
            BaseBIDEntry(
                base_bid="00001",
                behavior_name="behavior",
                behavior_description="e2e feature_id behavior",
                depends_on=[],
                notes="",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="00001-0001",
                        scenario_name="scenario-A",
                        gherkin_body="Scenario: scenario-A\n  Given x\n",
                        scenario_text_hash="00001-0001",
                        lifecycle_status=LifecycleStatus.APPROVED,
                        tests=[],
                        derivations=[],
                    ),
                ],
                behavior_halt=[],
            ),
        ],
        behavior_halt=[],
    )
    await mapping.save(project_dir / "mapping.yaml")

    # The pipeline needs both files to exist on disk.
    (project_dir / "plan.md").touch()
    (project_dir / "events.jsonl").touch()

    # Finalize the plan so the pipeline-start P4 check passes.
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    plan_path = project_dir / "plan.md"
    log = EventsLog(project_dir / "events.jsonl")
    await PlanArtifact.finalize(plan_path, "# e2e fixture plan\n", log)

    return project_dir


def _install_runner(monkeypatch: pytest.MonkeyPatch, runner_factory) -> None:
    """Install a runner factory, restoring the import-time capture for ``None``.

    Capturing the real factory before patching avoids resolving the patched
    module attribute when a test needs to restore the default implementation.
    """
    if runner_factory is None:
        monkeypatch.setattr("mage.cli._make_dry_run_runner", _REAL_DRY_RUN_RUNNER)
    else:
        monkeypatch.setattr("mage.cli._make_dry_run_runner", runner_factory)


def _make_halting_runner():
    """Return a runner factory that halts on the first scenario call.

    The runner sets ``context.automation_cursor`` and then raises
    ``ScenarioInspectHalted``; the graph catches the halt and persists
    ``pipeline-state.yaml`` so the assertion can read ``feature_id`` back.
    """

    from mage.orchestration.etch import ScenarioInspectHalted
    from mage.orchestration.runner import AutomationCursor

    def _factory(log, host_config, *, feature_id: str = ""):
        class _RaisingRunner:
            async def run(self, context, targets, *, cursor=None):
                target = targets[0]
                sub_bid = target.sub_bid
                context.automation_cursor = AutomationCursor(
                    sub_bid=sub_bid,
                    increment_index=0,
                    iteration=1,
                )
                raise ScenarioInspectHalted(
                    f"e2e feature_id halt: forced for {sub_bid!r}"
                )

        return _RaisingRunner()

    return _factory


@pytest.mark.asyncio
async def test_e2e_run_with_feature_id_threads_to_events(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mage run --feature-id feat-X persists feature_id on halt."""
    project_dir = await _plant_feature_id_fixture(tmp_path / "proj")

    _install_runner(monkeypatch, _make_halting_runner())

    # `main()` calls `asyncio.run` which conflicts with the running event
    # loop; run it in a thread so the SystemExit(0) surfaces here.
    with pytest.raises(SystemExit) as exc_info:
        exc_box: list[BaseException] = []

        def _thread_main() -> None:
            try:
                main(
                    [
                        "run",
                        "--dry-run",
                        "--project-dir",
                        str(project_dir),
                        "--feature-id",
                        "feat-X",
                    ]
                )
            except BaseException as exc:  # noqa: BLE001
                exc_box.append(exc)

        thread = threading.Thread(target=_thread_main)
        thread.start()
        thread.join()
        if exc_box:
            raise exc_box[0]

    assert exc_info.value.code == 0

    state_path = project_dir / ".mage" / "state" / "pipeline-state.yaml"
    assert state_path.exists(), "pipeline-state.yaml must be written on halt"

    state = yaml.safe_load(state_path.read_text())
    assert state.get("feature_id") == "feat-X", (
        f"Persisted state must record feature_id='feat-X'; got {state.get('feature_id')!r}"
    )


def test_e2e_run_without_feature_id_preserves_default(tmp_path) -> None:
    """mage run (no flag) --dry-run completes without error on empty project."""
    project = tmp_path / "proj"
    _setup_empty_project(project)

    rc = main(["run", "--project-dir", str(project), "--dry-run"])
    assert rc in (None, 0)
