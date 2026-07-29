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


def _reversion_log_for(mapping: MappingArtifact, sub_bid: str) -> list:
    for entry in mapping.base_bids:
        if any(s.sub_bid == sub_bid for s in entry.scenarios):
            return list(entry.reversion_log)
    return []


def test_stage_idempotent_on_duplicate_revision_requested(tmp_path):
    """Replaying the same revision event must not duplicate state.

    Three dispatches of SCENARIO_REVISION_REQUESTED for the same sub_bid
    produce one reversion log entry, one SCENARIO_REVERTED_TO_INSCRIBING
    event, and one REVERSION_LOGGED event. The first dispatch is the
    legitimate revision; subsequent replays of the same event must be
    short-circuited so they neither append duplicate audit entries nor
    corrupt the reversion log.
    """
    ctx = _ctx(tmp_path, LifecycleStatus.APPROVED)
    stage = DisciplineStage(ctx.events_log)
    payload = {
        "sub_bid": "A",
        "reason": "r",
        "originating_stage": "inspect_loop",
    }
    for _ in range(3):
        stage._handle_event(
            ctx,
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SCENARIO_REVISION_REQUESTED,
                payload=payload,
            ),
        )

    # First dispatch is legitimate: APPROVED -> INSCRIBING.
    scenario = next(
        s for e in ctx.mapping.base_bids for s in e.scenarios if s.sub_bid == "A"
    )
    assert scenario.lifecycle_status == LifecycleStatus.INSCRIBING
    # Exactly one reversion log entry — replays do not duplicate.
    assert len(_reversion_log_for(ctx.mapping, "A")) == 1

    events = ctx.events_log.read_all()
    reverted = [
        e for e in events if e.event_type == EventType.SCENARIO_REVERTED_TO_INSCRIBING
    ]
    logged = [e for e in events if e.event_type == EventType.REVERSION_LOGGED]
    assert len(reverted) == 1
    assert len(logged) == 1


def test_stage_idempotent_on_duplicate_supersession_requested(tmp_path):
    """Replaying the same supersession event must not duplicate state.

    Three dispatches of SCENARIO_SUPERSESSION_REQUESTED for the same
    (old_sub_bid, new_sub_bid) pair produce one supersession reversion log
    entry for the old scenario.
    """
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
                        lifecycle_status=LifecycleStatus.INSCRIBING,
                    )
                ],
            ),
        ],
    )
    stage = DisciplineStage(ctx.events_log)
    for _ in range(3):
        stage._handle_event(
            ctx,
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SCENARIO_SUPERSESSION_REQUESTED,
                payload={"old_sub_bid": "O", "new_sub_bid": "N", "reason": "new spec"},
            ),
        )

    assert len(_reversion_log_for(ctx.mapping, "O")) == 1


def test_stage_idempotent_on_duplicate_scenario_live(tmp_path):
    """Replaying the same live event must not duplicate supersession completion.

    Three dispatches of SCENARIO_LIVE for the same new_sub_bid complete the
    supersession once: one SCENARIO_DEPRECATED event and one supersession-
    completion log entry.
    """
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
    for _ in range(3):
        stage._handle_event(
            ctx,
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SCENARIO_LIVE,
                payload={"sub_bid": "N"},
            ),
        )

    events = ctx.events_log.read_all()
    deprecated = [e for e in events if e.event_type == EventType.SCENARIO_DEPRECATED]
    assert len(deprecated) == 1
    # Old scenario: lifecycle_status flipped to DEPRECATED, exactly one
    # supersession-completion log entry appended.
    old = next(
        s for e in ctx.mapping.base_bids for s in e.scenarios if s.sub_bid == "O"
    )
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED
    assert old.superseded_by == "N"
    assert len(_reversion_log_for(ctx.mapping, "O")) == 1


def test_stage_scenario_approved_does_not_release_lock_held_by_other(tmp_path):
    """A stale SCENARIO_APPROVED for sub_bid B must not clear the lock for A."""
    from mage.orchestration.discipline.policy import acquire_cycle_lock

    ctx = _ctx(tmp_path, LifecycleStatus.APPROVED)
    acquire_cycle_lock(ctx, "A")
    assert ctx.current_sub_bid == "A"

    stage = DisciplineStage(ctx.events_log)
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_APPROVED,
            payload={"sub_bid": "B"},
        ),
    )
    assert ctx.current_sub_bid == "A"

    # A matching approval for "A" still releases.
    stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_APPROVED,
            payload={"sub_bid": "A"},
        ),
    )
    assert ctx.current_sub_bid is None
