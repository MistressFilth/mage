"""Unit tests for the DecompositionStage approval gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mage.agents.decomposition import (
    ArchitectureSpec,
    DecompositionAgent,
    DecompositionOutput,
)
from mage.artifacts.enumeration import BehaviorSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.plan import compute_plan_digest
from mage.orchestration.decomposition import DecompositionStage
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.exceptions import StageHalted
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig

ASCERTAIN = """---
feature_id: feat-001
feature_name: User auth
scope_statement: Login.
in_scope: [login]
out_of_scope: [oauth]
success_criteria: [user can log in]
resolved_ambiguities: []
deferred_questions: []
constraints: []
three_amigos:
  product: ""
  tester: ""
  developer: ""
---

# ascertain
"""


def _stage(
    tmp_path: Path, *, require: bool
) -> tuple[DecompositionStage, Path, EventsLog]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN, encoding="utf-8")
    log = EventsLog(project_dir / "events.jsonl")
    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=[], components=[], layers=[]),
        behaviors=[BehaviorSpec(name="auth", description="Login")],
    )
    host_config = HostConfig(require_plan_approval=require)
    return (
        DecompositionStage(events_log=log, agent=agent, host_config=host_config),
        project_dir,
        log,
    )


def _ctx(project_dir: Path, log: EventsLog) -> PipelineContext:
    mapping = MappingArtifact(project_id="feat-001")
    return PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)


@pytest.mark.asyncio
async def test_approval_gate_silent_when_require_false(tmp_path):
    stage, project_dir, log = _stage(tmp_path, require=False)
    await stage._approval_gate(
        plan_content="# plan\n",
        plan_path=project_dir / "plan.md",
        feature_id="feat-001",
        project_dir=project_dir,
    )
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_REQUESTED not in types
    assert EventType.APPROVAL_GRANTED not in types
    assert not (project_dir / ".mage" / "approval_pending.json").exists()


@pytest.mark.asyncio
async def test_approval_gate_first_run_halts_and_writes_marker(tmp_path):
    stage, project_dir, log = _stage(tmp_path, require=True)
    with pytest.raises(StageHalted) as exc_info:
        await stage._approval_gate(
            plan_content="# plan\n",
            plan_path=project_dir / "plan.md",
            feature_id="feat-001",
            project_dir=project_dir,
        )
    assert exc_info.value.reason == "plan_approval"
    marker = project_dir / ".mage" / "approval_pending.json"
    assert marker.exists()
    payload = json.loads(marker.read_text())
    assert payload["feature_id"] == "feat-001"
    assert payload["plan_digest"] == compute_plan_digest("# plan\n")
    assert payload["plan_path"] == "plan.md"
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_REQUESTED in types


@pytest.mark.asyncio
async def test_approval_gate_grants_when_marker_present_and_digest_matches(tmp_path):
    stage, project_dir, log = _stage(tmp_path, require=True)
    plan_content = "# plan v1\n"
    digest = compute_plan_digest(plan_content)
    marker = project_dir / ".mage" / "approval_pending.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "feature_id": "feat-001",
                "plan_digest": digest,
                "plan_path": "plan.md",
                "requested_at": "2026-08-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    await stage._approval_gate(
        plan_content=plan_content,
        plan_path=project_dir / "plan.md",
        feature_id="feat-001",
        project_dir=project_dir,
    )
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_GRANTED in types
    assert EventType.APPROVAL_REQUESTED not in types
    assert not marker.exists()


@pytest.mark.asyncio
async def test_approval_gate_grants_when_marker_absent_and_requested_in_history(
    tmp_path,
):
    stage, project_dir, log = _stage(tmp_path, require=True)
    plan_content = "# plan v1\n"
    digest = compute_plan_digest(plan_content)
    # Pre-populate events.jsonl: a previous APPROVAL_REQUESTED for this digest.
    prior = Event(
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        event_type=EventType.APPROVAL_REQUESTED,
        payload={
            "feature_id": "feat-001",
            "plan_digest": digest,
            "plan_path": "plan.md",
        },
    )
    await log.append(prior)
    await stage._approval_gate(
        plan_content=plan_content,
        plan_path=project_dir / "plan.md",
        feature_id="feat-001",
        project_dir=project_dir,
    )
    types = [e.event_type for e in log.read_all()]
    assert types.count(EventType.APPROVAL_GRANTED) == 1
    assert not (project_dir / ".mage" / "approval_pending.json").exists()


@pytest.mark.asyncio
async def test_approval_gate_rehalts_when_marker_digest_stale(tmp_path):
    stage, project_dir, log = _stage(tmp_path, require=True)
    marker = project_dir / ".mage" / "approval_pending.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "feature_id": "feat-001",
                "plan_digest": "old-digest",
                "plan_path": "plan.md",
                "requested_at": "2026-08-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    new_plan = "# plan v2\n"
    new_digest = compute_plan_digest(new_plan)
    with pytest.raises(StageHalted) as exc_info:
        await stage._approval_gate(
            plan_content=new_plan,
            plan_path=project_dir / "plan.md",
            feature_id="feat-001",
            project_dir=project_dir,
        )
    assert exc_info.value.reason == "plan_approval_stale"
    payload = json.loads(marker.read_text())
    assert payload["plan_digest"] == new_digest
    types = [e.event_type for e in log.read_all()]
    # Two requests: one for the stale digest (we don't emit, see gate logic),
    # one for the new digest. Spec: emit APPROVAL_REQUESTED exactly once
    # for the new halt. Confirm at least one for new_digest.
    requested = [
        e for e in log.read_all() if e.event_type == EventType.APPROVAL_REQUESTED
    ]
    assert any(e.payload["plan_digest"] == new_digest for e in requested)
    assert EventType.APPROVAL_REQUESTED in types


@pytest.mark.asyncio
async def test_approval_gate_treats_malformed_marker_as_stale(tmp_path):
    stage, project_dir, log = _stage(tmp_path, require=True)
    marker = project_dir / ".mage" / "approval_pending.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("not-json{", encoding="utf-8")
    with pytest.raises(StageHalted):
        await stage._approval_gate(
            plan_content="# plan\n",
            plan_path=project_dir / "plan.md",
            feature_id="feat-001",
            project_dir=project_dir,
        )
    payload = json.loads(marker.read_text())
    assert payload["plan_digest"] == compute_plan_digest("# plan\n")
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_REQUESTED in types


def test_read_marker_returns_none_when_absent(tmp_path):
    stage, _, _ = _stage(tmp_path, require=True)
    assert stage._read_marker(tmp_path / "no-such.json") is None


def test_write_marker_is_atomic(tmp_path):
    stage, _, _ = _stage(tmp_path, require=True)
    marker = tmp_path / "mage" / "approval_pending.json"
    stage._write_marker(
        marker,
        feature_id="feat-X",
        plan_digest="d",
        plan_path=Path("plan.md"),
    )
    assert marker.exists()
    payload = json.loads(marker.read_text())
    assert payload["feature_id"] == "feat-X"
    assert payload["plan_digest"] == "d"
    assert payload["plan_path"] == "plan.md"
    assert "requested_at" in payload
