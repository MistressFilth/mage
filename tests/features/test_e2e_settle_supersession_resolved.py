"""End-to-end test for Plan 28a — SCENARIO_SUPERSESSION_RESOLVED emission.

Drives ``SettleFeatureStage.run_settle`` end-to-end with a hand-crafted
mapping containing two scenarios (one supersedes the other) and asserts
the events log contains the new SCENARIO_SUPERSESSION_RESOLVED event,
then dispatches it through ``DisciplineStage._handle_event`` so the
deprecation path is exercised end-to-end and the old scenario's
``lifecycle_status`` flips to ``DEPRECATED``.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.discipline.stage import DisciplineStage
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.settle_feature import (
    GitEnvironment,
    SettleFeatureStage,
)


def _seed_project(project: Path) -> None:
    """Write the minimal files mage expects on disk and make the first commit."""
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


def _make_mapping_with_supersession() -> MappingArtifact:
    """Two scenarios in one base_bid: OLD is LIVE, NEW is LIVE + supersedes OLD.

    Both must be ``LIVE`` so the Plan 28a emission (gated on
    ``new.lifecycle_status == LIVE``) fires for the NEW scenario.
    """
    return MappingArtifact(
        project_id="e2e",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b",
                behavior_description="d",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="OLD",
                        scenario_name="scenario-old",
                        gherkin_body="Scenario: scenario-old\n  Given x\n",
                        scenario_text_hash="h-old",
                        lifecycle_status=LifecycleStatus.LIVE,
                        feature_id="feat-test",
                    ),
                    ScenarioEntry(
                        sub_bid="NEW",
                        scenario_name="scenario-new",
                        gherkin_body="Scenario: scenario-new\n  Given y\n",
                        scenario_text_hash="h-new",
                        lifecycle_status=LifecycleStatus.LIVE,
                        supersedes="OLD",
                        feature_id="feat-test",
                    ),
                ],
                behavior_halt=[],
            )
        ],
    )


class _StubStage(SettleFeatureStage):
    """Stub out ``_run_tests``, ``_load_ready_inspect``, ``_detect_environment``,
    ``_execute_disposition`` and ``_render_report`` so the test only
    exercises the emission path."""

    async def _load_ready_inspect(self, context, feature_id):  # type: ignore[override]
        return None

    async def _run_tests(self, **kwargs):  # type: ignore[override]
        return None

    def _detect_environment(self, project_dir):  # type: ignore[override]
        return GitEnvironment(
            git_dir=project_dir / ".git",
            common_dir=project_dir / ".git",
            worktree_root=project_dir,
            repo_root=project_dir,
            branch="feat-test",
            is_worktree=False,
        )

    async def _execute_disposition(self, **kwargs):  # type: ignore[override]
        return None

    @staticmethod
    def _render_report(**kwargs) -> str:  # type: ignore[override]
        return ""


def test_settle_emits_resolved_and_deprecates_old(tmp_path: Path) -> None:
    """A successful settle emits SCENARIO_SUPERSESSION_RESOLVED for each
    in-feature supersession pair, and DisciplineStage then deprecates the
    old scenario when it sees the event."""
    _seed_project(tmp_path)
    mapping = _make_mapping_with_supersession()
    events_log = EventsLog(tmp_path / "events.jsonl")
    context = PipelineContext(
        project_dir=tmp_path, mapping=mapping, events_log=events_log
    )
    stage = _StubStage(events_log)

    asyncio.run(
        stage.run_settle(
            context,
            feature_id="feat-test",
            disposition="pr_opened",
        )
    )

    events = events_log.read_all()
    resolved = [
        e for e in events if e.event_type == EventType.SCENARIO_SUPERSESSION_RESOLVED
    ]
    assert len(resolved) == 1, (
        f"expected exactly one SCENARIO_SUPERSESSION_RESOLVED event; "
        f"got {len(resolved)} (events: "
        f"{[e.event_type.value for e in events]})"
    )
    assert resolved[0].payload == {
        "new_sub_bid": "NEW",
        "old_sub_bid": "OLD",
        "originating_stage": "settle",
    }

    # Dispatch the resolved event through DisciplineStage so the e2e flow
    # also exercises the deprecation path: complete_supersession must flip
    # OLD to DEPRECATED and the SCENARIO_DEPRECATED event is emitted.
    discipline = DisciplineStage(events_log)
    new_context = PipelineContext(
        project_dir=tmp_path, mapping=mapping, events_log=events_log
    )
    asyncio.run(discipline._handle_event(new_context, resolved[0]))
    base_bid = new_context.mapping.highest_base_bid()
    assert base_bid is not None
    old = new_context.mapping.lookup_sub_bid(base_bid, "OLD")
    assert old is not None
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED, (
        f"expected OLD scenario DEPRECATED after discipline resolves; "
        f"got {old.lifecycle_status}"
    )

    events = events_log.read_all()
    deprecated = [e for e in events if e.event_type == EventType.SCENARIO_DEPRECATED]
    assert len(deprecated) == 1
    assert deprecated[0].payload["old_sub_bid"] == "OLD"
    assert deprecated[0].payload["new_sub_bid"] == "NEW"


def test_settle_skips_resolved_on_discarded(tmp_path: Path) -> None:
    """disposition=discarded → zero SCENARIO_SUPERSESSION_RESOLVED events.

    Mirrors the existing SCENARIO_SUPERSESSION_REQUESTED skip rule: the
    P28a emission must respect the same gate.
    """
    _seed_project(tmp_path)
    mapping = _make_mapping_with_supersession()
    events_log = EventsLog(tmp_path / "events.jsonl")

    class _DiscardStubStage(_StubStage):
        async def _execute_disposition(self, **kwargs):  # type: ignore[override]
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SETTLE_BRANCH_DISCARDED,
                    payload={"feature_id": "feat-test"},
                )
            )

    context = PipelineContext(
        project_dir=tmp_path, mapping=mapping, events_log=events_log
    )
    stage = _DiscardStubStage(events_log)

    asyncio.run(
        stage.run_settle(
            context,
            feature_id="feat-test",
            disposition="discarded",
        )
    )

    events = events_log.read_all()
    resolved = [
        e for e in events if e.event_type == EventType.SCENARIO_SUPERSESSION_RESOLVED
    ]
    assert resolved == [], (
        f"SCENARIO_SUPERSESSION_RESOLVED must NOT be emitted for "
        f"disposition=discarded; got {len(resolved)}"
    )
