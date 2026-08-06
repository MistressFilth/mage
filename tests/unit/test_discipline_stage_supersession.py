"""Unit tests for Plan 28a — SCENARIO_SUPERSESSION_RESOLVED discipline branch.

The new event is emitted by SettleFeatureStage after a successful
disposition. The discipline branch delegates to the same helper used
by SCENARIO_LIVE (extracted in P28a Task 2), which calls
``complete_supersession`` and emits ``SCENARIO_DEPRECATED``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.discipline.stage import DisciplineStage
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext


def _ctx_with_supersession(tmp_path: Path) -> PipelineContext:
    """Build a context where new scenario supersedes old, both LIVE."""
    m = MappingArtifact(
        project_id="p",
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
                    ),
                    ScenarioEntry(
                        sub_bid="NEW",
                        scenario_name="scenario-new",
                        gherkin_body="Scenario: scenario-new\n  Given y\n",
                        scenario_text_hash="h-new",
                        lifecycle_status=LifecycleStatus.LIVE,
                        supersedes="OLD",
                    ),
                ],
                behavior_halt=[],
            )
        ],
    )
    return PipelineContext(
        project_dir=tmp_path,
        mapping=m,
        events_log=EventsLog(tmp_path / "events.jsonl"),
    )


@pytest.mark.asyncio
async def test_resolved_event_deprecates_old(tmp_path: Path) -> None:
    ctx = _ctx_with_supersession(tmp_path)
    stage = DisciplineStage(ctx.events_log)
    await stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_SUPERSESSION_RESOLVED,
            payload={
                "new_sub_bid": "NEW",
                "old_sub_bid": "OLD",
                "originating_stage": "settle",
            },
        ),
    )
    base_bid = ctx.mapping.highest_base_bid()
    assert base_bid is not None
    old = ctx.mapping.lookup_sub_bid(base_bid, "OLD")
    assert old is not None
    assert old.lifecycle_status == LifecycleStatus.DEPRECATED
    assert old.superseded_by == "NEW"


@pytest.mark.asyncio
async def test_resolved_event_emits_scenario_deprecated(tmp_path: Path) -> None:
    ctx = _ctx_with_supersession(tmp_path)
    stage = DisciplineStage(ctx.events_log)
    await stage._handle_event(
        ctx,
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.SCENARIO_SUPERSESSION_RESOLVED,
            payload={
                "new_sub_bid": "NEW",
                "old_sub_bid": "OLD",
                "originating_stage": "settle",
            },
        ),
    )
    events = ctx.events_log.read_all()
    deprecated = [
        e for e in events if e.event_type == EventType.SCENARIO_DEPRECATED
    ]
    assert len(deprecated) == 1
    assert deprecated[0].payload.get("old_sub_bid") == "OLD"
    assert deprecated[0].payload.get("new_sub_bid") == "NEW"


@pytest.mark.asyncio
async def test_resolved_event_is_idempotent_on_repeat(tmp_path: Path) -> None:
    ctx = _ctx_with_supersession(tmp_path)
    stage = DisciplineStage(ctx.events_log)
    evt = Event(
        timestamp=datetime.now(UTC),
        event_type=EventType.SCENARIO_SUPERSESSION_RESOLVED,
        payload={
            "new_sub_bid": "NEW",
            "old_sub_bid": "OLD",
            "originating_stage": "settle",
        },
    )
    await stage._handle_event(ctx, evt)
    # Capture reversion log length after first dispatch.
    base_bid = ctx.mapping.highest_base_bid()
    assert base_bid is not None
    first_log_len = len(ctx.mapping.base_bids[0].reversion_log)
    # Second dispatch is a no-op (seen-events guard).
    await stage._handle_event(ctx, evt)
    events = ctx.events_log.read_all()
    deprecated = [
        e for e in events if e.event_type == EventType.SCENARIO_DEPRECATED
    ]
    assert len(deprecated) == 1
    assert len(ctx.mapping.base_bids[0].reversion_log) == first_log_len