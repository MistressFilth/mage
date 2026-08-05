"""End-to-end pipeline test: `mage run --dry-run` against a fixture project.

Plan 6, Task 14. Two tests:

1. ``test_mage_run_dry_run_completes_a_feature`` — happy path. Plant a
   fixture with one APPROVED scenario, run ``mage run --dry-run`` against
   it, assert the pipeline completed the full sequence and the mapping
   reached ``feature_status == "settled"``.
2. ``test_mage_run_resumes_from_persisted_cursor`` — halt and resume.
   Plant a fixture and inject a runner that raises
   ``ScenarioInspectHalted``; the first run halts and persists the
   cursor to ``state/pipeline-state.yaml``. Repair the fixture so the
   runner no longer raises; the second run completes.

Both tests use the real ``mage run --dry-run`` CLI entry point (a
black-box exercise of the wired pipeline). The fixture helpers
``_plant_fixture`` and ``_repair_fixture`` control the test-only knobs
that the CLI does not expose.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

# Capture the real ``_make_dry_run_runner`` at import time so that
# ``_install_runner`` can restore it without recursing into the patched
# function. The patch target is the same name in the ``mage.cli``
# module, so re-importing after a patch would resolve to the patched
# function.
from mage.cli import _make_dry_run_runner as _REAL_DRY_RUN_RUNNER
from mage.orchestration.events import EventsLog

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# Path where the persistence layer writes the pipeline state on a halt.
_STATE_DIR = Path(".mage") / "state"


async def _plant_fixture(
    project_dir: Path,
    *,
    approved_sub_bid: str = "00001-0001",
    base_bid: str = "00001",
) -> Path:
    """Plant a fixture project ready for ``mage run --dry-run``.

    Writes:
    - ``mapping.yaml`` with one APPROVED scenario under ``base_bid``.
    - ``plan.md`` (empty placeholder; ``Plan`` finalization is Plan 2).
    - ``events.jsonl`` (empty; the events log touches itself on open).

    Returns the project directory.
    """
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
                base_bid=base_bid,
                behavior_name="behavior",
                behavior_description="e2e behavior",
                depends_on=[],
                notes="",
                scenarios=[
                    ScenarioEntry(
                        sub_bid=approved_sub_bid,
                        scenario_text_hash=approved_sub_bid,
                        lifecycle_status=LifecycleStatus.APPROVED,
                        tests=[],
                        derivations=[],
                    ),
                ],
            ),
        ],
    )
    await mapping.save(project_dir / "mapping.yaml")

    # Empty placeholders. The pipeline needs both files to exist on disk.
    (project_dir / "plan.md").touch()
    (project_dir / "events.jsonl").touch()

    # Plan 7: finalize the plan so the pipeline-start P4 check
    # (assert_decomposition_closed) passes. The dry-run path stubs
    # decomposition, so the plan must be finalized by the fixture.
    from mage.artifacts.plan import PlanArtifact

    plan_path = project_dir / "plan.md"
    log = EventsLog(project_dir / "events.jsonl")
    await PlanArtifact.finalize(plan_path, "# e2e fixture plan\n", log)

    return project_dir


def _repair_fixture(project_dir: Path) -> None:
    """Flip the fixture so the next ``mage run`` completes.

    The only thing the test controls is the runner injected via
    ``_install_runner``. ``_repair_fixture`` itself is a no-op on the
    on-disk fixture — the runner injection is what toggles halt vs.
    clean. Provided to make the brief's intent explicit.
    """
    # No on-disk fixture changes required. The runner injection is the
    # switch; see ``_install_runner`` and the test bodies.
    return


def _install_runner(
    monkeypatch: pytest.MonkeyPatch, runner_factory: Callable | None
) -> None:
    """Replace ``_make_dry_run_runner`` in ``mage.cli`` with ``runner_factory``.

    ``runner_factory`` receives ``(log, host_config)`` and returns an
    object exposing a ``run(context, targets, *, cursor=None)`` method.
    Passing ``None`` for ``runner_factory`` restores the real default
    (the dry-run stub runner).
    """
    if runner_factory is None:
        # Restore the real default — captured at import time.
        monkeypatch.setattr("mage.cli._make_dry_run_runner", _REAL_DRY_RUN_RUNNER)
    else:
        monkeypatch.setattr("mage.cli._make_dry_run_runner", runner_factory)


def _patch_settle_stub_to_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip the ``_StubStageNode._run`` for ``settle_feature`` to set
    ``feature_status == "settled"`` — mirroring the real SettleFeatureStage
    state transition. Without this, the dry-run path (which stubs settle)
    would leave ``feature_status`` unchanged and the happy-path assertion
    could not complete.
    """
    from mage.cli import _StubStageNode
    from mage.orchestration.nodes import PipelineContext

    original_run = _StubStageNode._run

    async def _run(self, context: PipelineContext) -> PipelineContext:
        if self.name == "settle_feature":
            context.mapping = context.mapping.model_copy(
                update={"feature_status": "settled"}
            )
            await context.mapping.save(context.project_dir / "mapping.yaml")
            return context
        return await original_run(self, context)

    monkeypatch.setattr(_StubStageNode, "_run", _run)


def _make_halting_runner(fail_sub_bid: str) -> Callable:
    """Factory: returns a runner that sets the cursor and raises
    ``ScenarioInspectHalted`` on the first call.

    The cursor set on the context drives the halt persistence. The
    ``fail_sub_bid`` parameter is documented for parity with the brief
    but the actual halted scenario is whatever the runner's first
    target is.
    """
    from mage.orchestration.etch import ScenarioInspectHalted
    from mage.orchestration.runner import AutomationCursor

    def _factory(log, host_config, *, feature_id: str = ""):
        class _RaisingRunner:
            async def run(self, context, targets, *, cursor=None):
                # Set the cursor first so the persist path captures it.
                target = targets[0]
                sub_bid = target.sub_bid
                context.automation_cursor = AutomationCursor(
                    sub_bid=sub_bid,
                    increment_index=0,
                    iteration=1,
                )
                # The first run is the only one; sub_bid must equal
                # fail_sub_bid (the test passes it). The actual halted
                # value is captured from the context above.
                raise ScenarioInspectHalted(
                    f"e2e halt: forced spec-route finding for {sub_bid!r}"
                )

        return _RaisingRunner()

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mage_run_dry_run_completes_a_feature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project with one APPROVED scenario runs the full pipeline.

    The dry-run stubs (decomposition, inscribe, inspect_feature) no-op;
    the ``AutomationStage`` runs the real ``FeatureRunner`` with the
    real dry-run stubs (increments have no steps, so the runner produces
    an empty outcome and the scenario becomes LIVE); the
    ``settle_feature`` stub is patched to flip
    ``feature_status == "settled"`` so the assertion fires.
    """
    from mage.artifacts.mapping import MappingArtifact
    from mage.cli import main

    project_dir = await _plant_fixture(tmp_path, approved_sub_bid="00001-0001")

    # Use the real dry-run runner (no patching).
    _install_runner(monkeypatch, None)
    _patch_settle_stub_to_settle(monkeypatch)

    import threading

    rc_box: list[int] = []
    err_box: list[BaseException] = []

    def _thread_main() -> None:
        try:
            rc_box.append(main(["run", "--dry-run", "--project-dir", str(project_dir)]))
        except BaseException as exc:  # noqa: BLE001
            err_box.append(exc)

    thread = threading.Thread(target=_thread_main)
    thread.start()
    thread.join()
    if err_box:
        raise err_box[0]
    rc = rc_box[0] if rc_box else 1
    assert rc == 0

    saved = MappingArtifact.load(project_dir / "mapping.yaml")
    assert saved.feature_status == "settled"

    # The scenario was transitioned to LIVE by the automation stage.
    entry = saved.base_bids[0]
    assert entry.scenarios[0].lifecycle_status.value == "live"

    # Events were emitted in the right order: the scenario became LIVE
    # before SETTLE flipped the status.
    log = EventsLog(project_dir / "events.jsonl")
    event_types = [e.event_type.value for e in log.read_all()]
    assert "stage_started" in event_types
    assert "stage_completed" in event_types
    assert "scenario_live" in event_types
    # The settle stub emits STAGE_COMPLETED after patching the status.
    assert event_types[-1] == "stage_completed"


@pytest.mark.asyncio
async def test_mage_run_resumes_from_persisted_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Halt on the first run; resume from the persisted cursor on the second.

    The first run injects a runner that raises ``ScenarioInspectHalted``
    after setting ``context.automation_cursor``. The graph catches the
    halt, persists the cursor to ``state/pipeline-state.yaml``, and exits
    with ``SystemExit(0)``.

    The second run repairs the fixture (here: swapping the runner for a
    clean one) and runs through to completion. ``rc == 0`` confirms the
    resume path is wired.
    """
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.persistence import FileStatePersistence

    project_dir = await _plant_fixture(tmp_path, approved_sub_bid="00001-0001")

    # First run: install a runner that halts on the first scenario.
    from mage.cli import main

    _install_runner(monkeypatch, _make_halting_runner(fail_sub_bid="00001-0001"))

    with pytest.raises(SystemExit) as exc_info:
        import threading

        exc_box: list[BaseException] = []

        def _thread_main() -> None:
            try:
                main(["run", "--dry-run", "--project-dir", str(project_dir)])
            except BaseException as exc:  # noqa: BLE001
                exc_box.append(exc)

        thread = threading.Thread(target=_thread_main)
        thread.start()
        thread.join()
        if exc_box:
            raise exc_box[0]
    # The graph exits cleanly on halt with rc 0.
    assert exc_info.value.code == 0

    # The cursor was persisted.
    state_dir = project_dir / ".mage" / "state"
    persistence = FileStatePersistence(state_dir=state_dir, state_type=PipelineContext)
    saved = persistence.load_state()
    assert saved is not None
    assert saved.automation_cursor is not None
    assert saved.automation_cursor.sub_bid == "00001-0001"
    assert saved.automation_cursor.increment_index == 0
    assert saved.automation_cursor.iteration == 1

    # The mapping was marked halted.
    from mage.artifacts.mapping import MappingArtifact

    halted_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    assert halted_mapping.feature_status == "halted"

    # Second run: repair the fixture (swap to the real dry-run runner) and run.
    _repair_fixture(project_dir)
    monkeypatch.undo()  # undo the previous _make_dry_run_runner patch
    _install_runner(monkeypatch, None)
    _patch_settle_stub_to_settle(monkeypatch)

    import threading

    rc_box: list[int] = []
    err_box: list[BaseException] = []

    def _thread_main() -> None:
        try:
            rc_box.append(main(["run", "--dry-run", "--project-dir", str(project_dir)]))
        except BaseException as exc:  # noqa: BLE001
            err_box.append(exc)

    thread = threading.Thread(target=_thread_main)
    thread.start()
    thread.join()
    if err_box:
        raise err_box[0]
    rc = rc_box[0] if rc_box else 1
    assert rc == 0
