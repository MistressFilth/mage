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


def _ctx(
    tmp_path: Path, scenario_status: LifecycleStatus = LifecycleStatus.LIVE
) -> PipelineContext:
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b",
                behavior_description="d",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="A",
                        scenario_text_hash="h",
                        lifecycle_status=scenario_status,
                    )
                ],
            )
        ],
    )
    return PipelineContext(
        project_dir=tmp_path, mapping=m, events_log=EventsLog(tmp_path / "events.jsonl")
    )


def test_stage_releases_lock_on_scenario_approved(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.APPROVED)
    ctx.current_sub_bid = "A"
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_APPROVED,
            payload={"sub_bid": "A"},
        ),
    )
    assert ctx.current_sub_bid is None


def test_stage_calls_begin_revision_on_revision_requested(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.LIVE)
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_REVISION_REQUESTED,
            payload={
                "sub_bid": "A",
                "reason": "r",
                "originating_stage": "inspect_loop",
            },
        ),
    )
    new_status = ctx.mapping.lookup_sub_bid(
        ctx.mapping.highest_base_bid(), "A"
    ).lifecycle_status
    assert new_status == LifecycleStatus.INSCRIBING


def test_stage_calls_begin_supersession_on_supersession_requested(tmp_path):
    new_entry = BaseBIDEntry(
        base_bid="00001",
        behavior_name="b1",
        behavior_description="d1",
        scenarios=[
            ScenarioEntry(
                sub_bid="N",
                scenario_text_hash="h",
                lifecycle_status=LifecycleStatus.INSCRIBING,
            )
        ],
    )
    ctx = _ctx(tmp_path)
    ctx.mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b0",
                behavior_description="d0",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="O",
                        scenario_text_hash="h",
                        lifecycle_status=LifecycleStatus.LIVE,
                    )
                ],
            ),
            new_entry,
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_SUPERSESSION_REQUESTED,
            payload={"old_sub_bid": "O", "new_sub_bid": "N", "reason": "new spec"},
        ),
    )
    new = next(
        s for e in ctx.mapping.base_bids for s in e.scenarios if s.sub_bid == "N"
    )
    assert new.supersedes == "O"


def test_stage_completes_pending_supersession_on_scenario_live(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b0",
                behavior_description="d0",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="O",
                        scenario_text_hash="h",
                        lifecycle_status=LifecycleStatus.LIVE,
                    )
                ],
            ),
            BaseBIDEntry(
                base_bid="00001",
                behavior_name="b1",
                behavior_description="d1",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="N",
                        scenario_text_hash="h",
                        lifecycle_status=LifecycleStatus.APPROVED,
                        supersedes="O",
                    )
                ],
            ),
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_LIVE,
            payload={"sub_bid": "N"},
        ),
    )
    old = next(
        s for e in ctx.mapping.base_bids for s in e.scenarios if s.sub_bid == "O"
    )
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED
    assert old.superseded_by == "N"


def test_stage_idempotent_on_duplicate_scenario_approved(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.APPROVED)
    ctx.current_sub_bid = "A"
    stage = DisciplineStage(ctx.events_log)
    for _ in range(3):
        stage._handle_event(
            ctx,
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SCENARIO_APPROVED,
                payload={"sub_bid": "A"},
            ),
        )
    assert ctx.current_sub_bid is None


def test_stage_emits_reverted_event_on_revision(tmp_path):
    ctx = _ctx(tmp_path, LifecycleStatus.LIVE)
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_REVISION_REQUESTED,
            payload={
                "sub_bid": "A",
                "reason": "r",
                "originating_stage": "inspect_loop",
            },
        ),
    )
    events = ctx.events_log.read_all()
    assert any(
        e.event_type == EventType.SCENARIO_REVERTED_TO_INSCRIBING for e in events
    )
    assert any(e.event_type == EventType.REVERSION_LOGGED for e in events)


def test_stage_emits_deprecated_event_on_supersession_complete(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b0",
                behavior_description="d0",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="O",
                        scenario_text_hash="h",
                        lifecycle_status=LifecycleStatus.LIVE,
                    )
                ],
            ),
            BaseBIDEntry(
                base_bid="00001",
                behavior_name="b1",
                behavior_description="d1",
                scenarios=[
                    ScenarioEntry(
                        sub_bid="N",
                        scenario_text_hash="h",
                        lifecycle_status=LifecycleStatus.APPROVED,
                        supersedes="O",
                    )
                ],
            ),
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_LIVE,
            payload={"sub_bid": "N"},
        ),
    )
    events = ctx.events_log.read_all()
    assert any(e.event_type == EventType.SCENARIO_DEPRECATED for e in events)
