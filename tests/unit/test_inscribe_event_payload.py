"""Unit tests for InscribeStage INSCRIBE_STARTED payload feature_id (Plan 13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.inscribe import InscribeStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig


@pytest.fixture(autouse=True)
def use_test_model():
    """Force Pydantic-AI agents to use TestModel for deterministic tests."""
    models.ALLOW_MODEL_REQUESTS = False
    yield


def _seed_project(tmp_path: Path) -> Path:
    """Create a project tree with behaviors.yaml and a matching mapping.yaml."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": "feat-1",
                "enumerated_at": "2026-07-27T00:00:00Z",
                "behaviors": [],
            }
        )
    )
    (project / ".haileris").mkdir(exist_ok=True)
    return project


def _make_inscribe_stage(events_log: EventsLog) -> InscribeStage:
    """Build an InscribeStage with reviewers=[] (skips LLM reviewer fan-out).

    Construction mirrors the project's existing test pattern in
    tests/unit/test_inscribe_stage.py: one InscribeAgent backed by TestModel,
    one HostConfig with a small max_iterations, and no reviewers.
    """
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=None))
    host_config = HostConfig(max_iterations=1)
    return InscribeStage(
        events_log=events_log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=[],
    )


@pytest.mark.asyncio
async def test_inscribe_started_event_carries_context_feature_id(tmp_path):
    """INSCRIBE_STARTED payload's feature_id == context.feature_id (NOT 'unknown')."""
    project = _seed_project(tmp_path)
    events_log_path = project / "events.jsonl"
    events_log = EventsLog(events_log_path)

    mapping = MappingArtifact(
        schema_version=2,
        project_id="p",
        base_bids=[
            {
                "base_bid": "00000",
                "behavior_name": "authenticate-user",
                "behavior_description": "User logs in",
                "depends_on": [],
                "notes": "",
                "scenarios": [],
                "reversion_log": [],
                "post_live_revisions": [],
                "cross_behavior_links": [],
            }
        ],
    )
    await mapping.save(project / "mapping.yaml")

    context = PipelineContext(
        project_dir=project,
        mapping=mapping,
        events_log=events_log,
        plan_path=project / "plan.md",
        feature_id="feat-Y",
    )

    stage = _make_inscribe_stage(events_log)

    try:
        await stage._run(context)
    except BaseException:  # noqa: BLE001, S110
        pass  # we only care about the STARTED event emission, which happens first

    assert events_log_path.exists(), "events.jsonl was not written"
    lines = events_log_path.read_text().strip().splitlines()
    started = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("event_type") == "inscribe_started"
    ]
    assert started, "expected INSCRIBE_STARTED event in events.jsonl"
    payload = started[0]["payload"]
    assert payload["feature_id"] == "feat-Y"
    assert payload["feature_id"] != "unknown"


@pytest.mark.asyncio
async def test_inscribe_started_event_empty_when_context_feature_id_empty(tmp_path):
    """Default empty feature_id propagates as '' (not 'unknown')."""
    project = _seed_project(tmp_path)
    events_log_path = project / "events.jsonl"
    events_log = EventsLog(events_log_path)

    mapping = MappingArtifact(
        schema_version=2,
        project_id="p",
        base_bids=[
            {
                "base_bid": "00000",
                "behavior_name": "authenticate-user",
                "behavior_description": "User logs in",
                "depends_on": [],
                "notes": "",
                "scenarios": [],
                "reversion_log": [],
                "post_live_revisions": [],
                "cross_behavior_links": [],
            }
        ],
    )
    await mapping.save(project / "mapping.yaml")

    context = PipelineContext(
        project_dir=project,
        mapping=mapping,
        events_log=events_log,
        plan_path=project / "plan.md",
        feature_id="",
    )

    stage = _make_inscribe_stage(events_log)

    try:
        await stage._run(context)
    except BaseException:  # noqa: BLE001, S110
        pass

    lines = events_log_path.read_text().strip().splitlines()
    started = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("event_type") == "inscribe_started"
    ]
    assert started
    payload = started[0]["payload"]
    assert payload["feature_id"] == ""
    assert payload["feature_id"] != "unknown"


@pytest.mark.asyncio
async def test_inscribe_completed_event_carries_context_feature_id(tmp_path):
    """INSCRIBE_COMPLETED payload's feature_id == context.feature_id (NOT 'unknown')."""
    project = _seed_project(tmp_path)
    events_log_path = project / "events.jsonl"
    events_log = EventsLog(events_log_path)

    mapping = MappingArtifact(schema_version=2, project_id="p", base_bids=[])
    await mapping.save(project / "mapping.yaml")

    context = PipelineContext(
        project_dir=project,
        mapping=mapping,
        events_log=events_log,
        plan_path=project / "plan.md",
        feature_id="feat-Y",
    )

    stage = _make_inscribe_stage(events_log)

    try:
        await stage._run(context)
    except BaseException:  # noqa: BLE001, S110
        pass

    lines = events_log_path.read_text().strip().splitlines()
    completed = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("event_type") == "inscribe_completed"
    ]
    assert completed, "expected INSCRIBE_COMPLETED event in events.jsonl"
    payload = completed[-1]["payload"]
    assert payload["feature_id"] == "feat-Y"
    assert payload["feature_id"] != "unknown"


@pytest.mark.asyncio
async def test_inscribe_completed_event_empty_when_context_feature_id_empty(tmp_path):
    """Default empty feature_id propagates as '' (not 'unknown')."""
    project = _seed_project(tmp_path)
    events_log_path = project / "events.jsonl"
    events_log = EventsLog(events_log_path)

    mapping = MappingArtifact(schema_version=2, project_id="p", base_bids=[])
    await mapping.save(project / "mapping.yaml")

    context = PipelineContext(
        project_dir=project,
        mapping=mapping,
        events_log=events_log,
        plan_path=project / "plan.md",
        feature_id="",
    )

    stage = _make_inscribe_stage(events_log)

    try:
        await stage._run(context)
    except BaseException:  # noqa: BLE001, S110
        pass

    lines = events_log_path.read_text().strip().splitlines()
    completed = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("event_type") == "inscribe_completed"
    ]
    assert completed
    payload = completed[-1]["payload"]
    assert payload["feature_id"] == ""
    assert payload["feature_id"] != "unknown"
