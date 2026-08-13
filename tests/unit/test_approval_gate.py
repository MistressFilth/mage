"""Unit tests for the DecompositionStage approval gate.

P32 task 13: the approval marker now lives on the mage orphan branch at
``approval_pending.json`` (Path: ``APPROVAL_PENDING_PATH``); the gate reads
and writes it through the injected ``StateStore`` instead of touching
``<project_dir>/.mage/approval_pending.json``. Tests exercise the
StateStore-based path so a working-tree file at the old location is
neither required nor sufficient.
"""

from __future__ import annotations

import json
import subprocess
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
from mage.orchestration.decomposition import APPROVAL_PENDING_PATH, DecompositionStage
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.exceptions import StageHalted
from mage.orchestration.nodes import PipelineContext
from mage.state_store import StateStore
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


def _init_git_repo(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


def _make_state_store(project_dir: Path) -> StateStore:
    _init_git_repo(project_dir)
    return StateStore(project_dir, "feature-artifacts", identity=("T", "t@e"))


def _stage(
    tmp_path: Path, *, require: bool
) -> tuple[DecompositionStage, Path, EventsLog, StateStore]:
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
    state_store = _make_state_store(tmp_path / "git")
    return (
        DecompositionStage(events_log=log, agent=agent, host_config=host_config),
        project_dir,
        log,
        state_store,
    )


def _ctx(project_dir: Path, log: EventsLog, state_store) -> PipelineContext:
    mapping = MappingArtifact(project_id="feat-001")
    return PipelineContext(
        state_store=state_store,
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
    )


@pytest.mark.asyncio
async def test_approval_gate_silent_when_require_false(tmp_path):
    stage, project_dir, log, state_store = _stage(tmp_path, require=False)
    await stage._approval_gate(
        plan_content="# plan\n",
        plan_path=project_dir / "plan.md",
        feature_id="feat-001",
        project_dir=project_dir,
        state_store=state_store,
    )
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_REQUESTED not in types
    assert EventType.APPROVAL_GRANTED not in types
    # P32: the orphan branch carries no marker after a no-op gate run.
    assert state_store.read(APPROVAL_PENDING_PATH) == b""


@pytest.mark.asyncio
async def test_approval_gate_first_run_halts_and_writes_marker(tmp_path):
    stage, project_dir, log, state_store = _stage(tmp_path, require=True)
    with pytest.raises(StageHalted) as exc_info:
        await stage._approval_gate(
            plan_content="# plan\n",
            plan_path=project_dir / "plan.md",
            feature_id="feat-001",
            project_dir=project_dir,
            state_store=state_store,
        )
    assert exc_info.value.reason == "plan_approval"
    raw = state_store.read(APPROVAL_PENDING_PATH)
    assert raw, "orphan-branch marker should be present after a first-run halt"
    payload = json.loads(raw)
    assert payload["feature_id"] == "feat-001"
    assert payload["plan_digest"] == compute_plan_digest("# plan\n")
    assert payload["plan_path"] == "plan.md"
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_REQUESTED in types


@pytest.mark.asyncio
async def test_approval_gate_grants_when_marker_present_and_digest_matches(tmp_path):
    stage, project_dir, log, state_store = _stage(tmp_path, require=True)
    plan_content = "# plan v1\n"
    digest = compute_plan_digest(plan_content)
    state_store.write(
        APPROVAL_PENDING_PATH,
        json.dumps(
            {
                "feature_id": "feat-001",
                "plan_digest": digest,
                "plan_path": "plan.md",
                "requested_at": "2026-08-01T00:00:00Z",
            }
        ).encode("utf-8"),
    )
    await stage._approval_gate(
        plan_content=plan_content,
        plan_path=project_dir / "plan.md",
        feature_id="feat-001",
        project_dir=project_dir,
        state_store=state_store,
    )
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_GRANTED in types
    assert EventType.APPROVAL_REQUESTED not in types
    assert state_store.read(APPROVAL_PENDING_PATH) == b""


@pytest.mark.asyncio
async def test_approval_gate_grants_when_marker_absent_and_requested_in_history(
    tmp_path,
):
    stage, project_dir, log, state_store = _stage(tmp_path, require=True)
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
        state_store=state_store,
    )
    types = [e.event_type for e in log.read_all()]
    assert types.count(EventType.APPROVAL_GRANTED) == 1
    assert state_store.read(APPROVAL_PENDING_PATH) == b""


@pytest.mark.asyncio
async def test_approval_gate_rehalts_when_marker_digest_stale(tmp_path):
    stage, project_dir, log, state_store = _stage(tmp_path, require=True)
    state_store.write(
        APPROVAL_PENDING_PATH,
        json.dumps(
            {
                "feature_id": "feat-001",
                "plan_digest": "old-digest",
                "plan_path": "plan.md",
                "requested_at": "2026-08-01T00:00:00Z",
            }
        ).encode("utf-8"),
    )
    new_plan = "# plan v2\n"
    new_digest = compute_plan_digest(new_plan)
    with pytest.raises(StageHalted) as exc_info:
        await stage._approval_gate(
            plan_content=new_plan,
            plan_path=project_dir / "plan.md",
            feature_id="feat-001",
            project_dir=project_dir,
            state_store=state_store,
        )
    assert exc_info.value.reason == "plan_approval_stale"
    payload = json.loads(state_store.read(APPROVAL_PENDING_PATH))
    assert payload["plan_digest"] == new_digest
    types = [e.event_type for e in log.read_all()]
    requested = [
        e for e in log.read_all() if e.event_type == EventType.APPROVAL_REQUESTED
    ]
    assert any(e.payload["plan_digest"] == new_digest for e in requested)
    assert EventType.APPROVAL_REQUESTED in types


@pytest.mark.asyncio
async def test_approval_gate_treats_malformed_marker_as_stale(tmp_path):
    stage, project_dir, log, state_store = _stage(tmp_path, require=True)
    state_store.write(APPROVAL_PENDING_PATH, b"not-json{")
    with pytest.raises(StageHalted) as exc_info:
        await stage._approval_gate(
            plan_content="# plan\n",
            plan_path=project_dir / "plan.md",
            feature_id="feat-001",
            project_dir=project_dir,
            state_store=state_store,
        )
    assert exc_info.value.reason == "plan_approval_stale"
    payload = json.loads(state_store.read(APPROVAL_PENDING_PATH))
    assert payload["plan_digest"] == compute_plan_digest("# plan\n")
    types = [e.event_type for e in log.read_all()]
    assert EventType.APPROVAL_REQUESTED in types


def test_read_marker_returns_none_when_absent(tmp_path):
    stage, _, _, _state_store = _stage(tmp_path, require=True)
    fresh_store = _make_state_store(tmp_path / "git_other")
    assert stage._read_marker(fresh_store) is None


def test_write_marker_is_atomic(tmp_path):
    stage, _, _, state_store = _stage(tmp_path, require=True)
    stage._write_marker(
        state_store,
        feature_id="feat-X",
        plan_digest="d",
        plan_path=Path("plan.md"),
    )
    raw = state_store.read(APPROVAL_PENDING_PATH)
    assert raw
    payload = json.loads(raw)
    assert payload["feature_id"] == "feat-X"
    assert payload["plan_digest"] == "d"
    assert payload["plan_path"] == "plan.md"
    assert "requested_at" in payload
