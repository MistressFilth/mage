"""End-to-end + static guard for Plan 14 (settle supersession).

Plan 14 wires ``SettleFeatureStage.run_settle`` so that a feature settled
with a non-discarded disposition emits one
``SCENARIO_SUPERSESSION_REQUESTED`` event per scenario whose ``feature_id``
matches the settled feature and whose ``supersedes`` field is set. This
module pins that wiring with two tests:

1. **Static guard** — grep the source tree for the literal ``TODO(plan8)``
   placeholder the plan closed. After Plan 14 the placeholder must not
   reappear in ``src/mage/``; this test fails loudly if it does.
2. **End-to-end** — drive ``SettleFeatureStage.run_settle`` end-to-end
   through the Python API (mirroring ``tests/unit/test_settle_emits_
   supersession.py`` and ``tests/features/test_e2e_inspect_settle.py``)
   with a real on-disk ``MappingArtifact.load(...)`` round-trip and a
   hand-crafted scenario carrying ``feature_id="feat-X"`` and
   ``supersedes="old-Y"``. Asserts the events.jsonl contains exactly one
   ``scenario_supersession_requested`` event with the expected payload.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import yaml

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.settle_feature import (
    GitEnvironment,
    SettleFeatureStage,
)

# ---------------------------------------------------------------------------
# Shared fixture seeding
# ---------------------------------------------------------------------------


def _seed_project(project: Path) -> None:
    """Write the minimal files mage expects on disk and make the first commit.

    Matches the seeding conventions used in
    ``tests/features/test_e2e_inspect_feature_id.py`` and
    ``tests/features/test_e2e_feature_id_sentinel_cleanup.py``: a git
    repository is initialised so the seeded files are commit-able, which
    mirrors what a real host project looks like when ``mage settle`` runs.
    """
    (project / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
    )
    (project / "behaviors.yaml").write_text("behaviors: []\n")
    (project / "plan.md").write_text("# plan\n")
    (project / ".mage").mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@mage"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "e2e"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)


# ---------------------------------------------------------------------------
# Static guard
# ---------------------------------------------------------------------------


def test_static_guard_no_plan8_todo_in_source() -> None:
    """After Plan 14, ``TODO(plan8)`` must not appear anywhere in ``src/mage/``.

    Task 3 already removed the placeholder block from
    ``settle_feature.py``. This guard pins the cleanup so any future
    regression that re-introduces the placeholder in source fails the
    build before a code review even starts.
    """
    result = subprocess.run(
        ["grep", "-rn", "TODO(plan8)", "src/mage"],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2],  # mage/ repo root
    )
    # grep returns 0 = matches found (regression), 1 = no matches (clean),
    # 2 = error. Asserting == 1 surfaces both the regression case AND any
    # grep invocation error rather than silently treating them as the same.
    assert result.returncode == 1, (
        f"Static guard failed: TODO(plan8) reappeared in source.\n"
        f"grep exit code: {result.returncode}\n"
        f"grep output:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# End-to-end: drive SettleFeatureStage.run_settle via the Python API
# ---------------------------------------------------------------------------


def _stub_stage(events_log: EventsLog) -> SettleFeatureStage:
    """Build a SettleFeatureStage with the git/test/disposition surface
    replaced by async no-ops.

    Mirrors the ``stubbed_stage`` fixture in
    ``tests/unit/test_settle_emits_supersession.py`` (Task 3): only the
    supersession emission block needs to run for real; everything around
    it is replaced so the test focuses on the wire and stays
    deterministic. ``__init__`` is bypassed because the stage is being
    constructed by hand to skip unrelated validation/host-config wiring.
    """
    stage = SettleFeatureStage.__new__(SettleFeatureStage)  # bypass __init__
    stage.events_log = events_log

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    def _fake_environment(project_dir: Path) -> GitEnvironment:
        return GitEnvironment(
            git_dir=project_dir / ".git",
            common_dir=project_dir / ".git",
            worktree_root=project_dir,
            repo_root=project_dir,
            branch="feature/test",
            is_worktree=False,
        )

    stage._load_ready_inspect = _noop  # type: ignore[method-assign, ty:invalid-assignment]
    stage._run_tests = _noop  # type: ignore[method-assign, ty:invalid-assignment]
    stage._detect_environment = _fake_environment  # type: ignore[method-assign, ty:invalid-assignment]
    stage._execute_disposition = _noop  # type: ignore[method-assign, ty:invalid-assignment]
    stage._render_report = staticmethod(  # type: ignore[method-assign, ty:invalid-assignment]
        lambda **_kwargs: ""
    )
    return stage


def test_e2e_settle_emits_supersession_for_supersede_scenario(tmp_path: Path) -> None:
    """A settle over a feature whose scenario has ``supersedes="old-Y"`` emits the event.

    The mapping is hand-crafted on disk and round-tripped through
    ``MappingArtifact.load(...)`` so the test exercises the real artifact
    deserializer (and its model validators) rather than constructing the
    artifact in-memory. ``SettleFeatureStage.run_settle`` is then driven
    via ``asyncio.run`` so the test reads as one synchronous pytest
    function and stays parallel to the rest of ``tests/features/``.
    """
    project = tmp_path / "proj"
    project.mkdir()
    _seed_project(project)

    # Hand-craft a mapping with one base_bid + one scenario tagged for
    # ``feat-X`` with ``supersedes="old-Y"``. Inscribe is bypassed; this
    # test pins the Settle emission only.
    mapping = {
        "schema_version": 2,
        "project_id": "p",
        "base_bids": [
            {
                "base_bid": "00000",
                "behavior_name": "b",
                "behavior_description": "",
                "depends_on": [],
                "notes": "",
                "scenarios": [
                    {
                        "sub_bid": "00000-001",
                        "scenario_text_hash": "abc",
                        "lifecycle_status": "approved",
                        "supersedes": "old-Y",
                        "superseded_by": None,
                        "feature_id": "feat-X",
                        "tests": [],
                        "derivations": [],
                    }
                ],
                "reversion_log": [],
                "post_live_revisions": [],
                "cross_behavior_links": [],
            }
        ],
    }
    mapping_path = project / "mapping.yaml"
    mapping_path.write_text(yaml.safe_dump(mapping))
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=project, check=True)

    events_log_path = project / "events.jsonl"
    events_log = EventsLog(events_log_path)
    loaded = MappingArtifact.load(mapping_path)
    context = PipelineContext(
        project_dir=project,
        mapping=loaded,
        events_log=str(events_log_path),
        feature_id="feat-X",
    )

    stage = _stub_stage(events_log)
    asyncio.run(stage.run_settle(context, feature_id="feat-X", disposition="merged"))

    assert events_log_path.exists(), "Settle did not write any events"
    events = [
        json.loads(line) for line in events_log_path.read_text().splitlines() if line
    ]
    supersession = [
        event
        for event in events
        if event["event_type"] == "scenario_supersession_requested"
    ]
    assert len(supersession) == 1, (
        f"expected exactly one scenario_supersession_requested event; "
        f"got {len(supersession)}\n"
        f"events: {[e['event_type'] for e in events]}"
    )
    payload = supersession[0]["payload"]
    assert payload["new_sub_bid"] == "00000-001"
    assert payload["old_sub_bid"] == "old-Y"
