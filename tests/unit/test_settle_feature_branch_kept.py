"""Unit test for Plan 29 — SETTLE_BRANCH_KEPT emission.

P29 closes the P26 Minor finding at settle_feature.py:443: the
`disposition="kept"` path early-returned without emitting any event,
violating the AGENTS.md "events are the audit trail" rule. This test
pins the new SETTLE_BRANCH_KEPT emission symmetric with the existing
SETTLE_BRANCH_DISCARDED.

Note: StageNode._emit injects {"stage": self.name} into every emitted
event; this test uses key-by-key access (per the P28a convention) to
avoid coupling to the injected stage key.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mage.orchestration.events import EventsLog, EventType
from mage.orchestration.settle_feature import (
    GitEnvironment,
    SettleFeatureStage,
)
from mage.verification.host_overrides import HostConfig


def _stub_stage(events_log: EventsLog) -> SettleFeatureStage:
    """Build a SettleFeatureStage with all collaborators stubbed."""
    stage = SettleFeatureStage.__new__(SettleFeatureStage)
    stage.events_log = events_log
    stage.host_config = HostConfig()
    return stage


def _env() -> GitEnvironment:
    return GitEnvironment(
        git_dir=Path("/tmp"),
        common_dir=Path("/tmp"),
        worktree_root=Path("/tmp"),
        repo_root=Path("/tmp"),
        branch="feat-test",
        is_worktree=False,
    )


def test_kept_disposition_emits_settle_branch_kept(tmp_path: Path) -> None:
    """When disposition='kept', the function must emit SETTLE_BRANCH_KEPT
    before returning, with payload {feature_id: <id>}."""
    events_log = EventsLog(tmp_path / "events.jsonl")
    stage = _stub_stage(events_log)
    asyncio.run(
        stage._execute_disposition(
            feature_id="00000",
            disposition="kept",
            environment=_env(),
        )
    )
    events = events_log.read_all()
    kept = [e for e in events if e.event_type == EventType.SETTLE_BRANCH_KEPT]
    assert len(kept) == 1
    assert kept[0].payload["feature_id"] == "00000"
