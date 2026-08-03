"""Unit tests for Settle.run_settle supersession event emission (Plan 14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mage.artifacts.mapping import (
    Base85BID,
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.settle_feature import GitEnvironment, SettleFeatureStage


def _make_pipeline_context(
    tmp_path, *, mapping, feature_id
) -> tuple[PipelineContext, Path]:
    events_log_path = tmp_path / "events.jsonl"
    context = PipelineContext(
        project_dir=tmp_path,
        mapping=mapping,
        events_log=str(events_log_path),
        feature_id=feature_id,
    )
    return context, events_log_path


def _make_mapping_with_supersede(
    *, feature_id: str, supersedes_old: str | None
) -> MappingArtifact:
    scenario = ScenarioEntry(
        sub_bid="00000-001",
        scenario_text_hash="abc",
        lifecycle_status=LifecycleStatus.APPROVED,
        supersedes=supersedes_old,
        feature_id=feature_id,
    )
    bid = Base85BID(value="00000")
    entry = BaseBIDEntry(
        base_bid=bid.value,
        behavior_name="b",
        behavior_description="d",
        scenarios=[scenario],
    )
    return MappingArtifact(schema_version=2, project_id="p", base_bids=[entry])


@pytest.fixture
def stubbed_stage():
    """Return a factory that builds a SettleFeatureStage with the git/MageRun
    surface replaced by async no-ops. Tests attach their own events_log and
    feature/mapping via the returned instance attributes."""

    def _factory(events_log: EventsLog):
        stage = SettleFeatureStage.__new__(SettleFeatureStage)  # bypass __init__
        stage.events_log = events_log

        async def _noop(*args, **kwargs):
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

        # These are called after the new emission block; replacing them lets
        # the test focus on the supersession event without exercising git,
        # MageRun, or test-command plumbing.
        stage._load_ready_inspect = _noop  # type: ignore[method-assign, ty:invalid-assignment]
        stage._run_tests = _noop  # type: ignore[method-assign, ty:invalid-assignment]
        stage._detect_environment = _fake_environment  # type: ignore[method-assign, ty:invalid-assignment]
        stage._execute_disposition = _noop  # type: ignore[method-assign, ty:invalid-assignment]
        stage._render_report = staticmethod(  # type: ignore[method-assign, ty:invalid-assignment]
            lambda **kwargs: ""
        )
        return stage

    return _factory


@pytest.mark.asyncio
async def test_settle_emits_supersession_for_matching_scenarios(
    tmp_path, stubbed_stage
):
    """One scenario tagged feat-X with supersedes=old-Y → one SCENARIO_SUPERSESSION_REQUESTED event."""
    mapping = _make_mapping_with_supersede(feature_id="feat-X", supersedes_old="old-Y")
    context, events_log_path = _make_pipeline_context(
        tmp_path, mapping=mapping, feature_id="feat-X"
    )

    stage = stubbed_stage(EventsLog(events_log_path))

    await stage.run_settle(context, feature_id="feat-X", disposition="merged")

    assert events_log_path.exists()
    events = [json.loads(l) for l in events_log_path.read_text().splitlines() if l]
    supersession = [
        e for e in events if e["event_type"] == "scenario_supersession_requested"
    ]
    assert len(supersession) == 1
    payload = supersession[0]["payload"]
    assert payload["new_sub_bid"] == "00000-001"
    assert payload["old_sub_bid"] == "old-Y"
    assert payload["reason"] == ""
    assert payload["originating_stage"] == "settle"


@pytest.mark.asyncio
async def test_settle_skips_emission_when_disposition_is_discarded(
    tmp_path, stubbed_stage
):
    """discarded → zero supersession events regardless of mapping content."""
    mapping = _make_mapping_with_supersede(feature_id="feat-X", supersedes_old="old-Y")
    context, events_log_path = _make_pipeline_context(
        tmp_path, mapping=mapping, feature_id="feat-X"
    )

    stage = stubbed_stage(EventsLog(events_log_path))

    await stage.run_settle(context, feature_id="feat-X", disposition="discarded")

    # Settle must always write SOMETHING to events.jsonl (e.g. SETTLE_FEATURE_STARTED).
    # Silent paths indicate a regression where the stage swallowed its work; this
    # assertion fails loud instead of silently returning.
    assert events_log_path.exists(), (
        "Settle wrote no events for disposition=discarded; expected at least "
        "SETTLE_FEATURE_STARTED"
    )
    events = [json.loads(l) for l in events_log_path.read_text().splitlines() if l]
    supersession = [
        e for e in events if e["event_type"] == "scenario_supersession_requested"
    ]
    assert supersession == [], (
        "supersession event must NOT be emitted for disposition=discarded"
    )


@pytest.mark.asyncio
async def test_settle_skips_scenarios_with_wrong_feature_id(tmp_path, stubbed_stage):
    """Scenario tagged for another feature → no emission (defensive skip)."""
    mapping = _make_mapping_with_supersede(
        feature_id="other-feature", supersedes_old="old-Y"
    )
    context, events_log_path = _make_pipeline_context(
        tmp_path, mapping=mapping, feature_id="feat-X"
    )

    stage = stubbed_stage(EventsLog(events_log_path))

    await stage.run_settle(context, feature_id="feat-X", disposition="merged")

    assert events_log_path.exists(), (
        "Settle wrote no events; expected at least SETTLE_FEATURE_STARTED "
        "even when no scenario supersedes"
    )
    events = [json.loads(l) for l in events_log_path.read_text().splitlines() if l]
    supersession = [
        e for e in events if e["event_type"] == "scenario_supersession_requested"
    ]
    assert supersession == [], (
        "must not emit when scenario.feature_id != settled feature"
    )
