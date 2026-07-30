"""Tests for ReviewerAgent base class."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.base import ReviewerAgent


class FakeReviewer(ReviewerAgent):
    dimension = "fake_dimension"

    def _system_prompt(self) -> str:
        return "You are a fake reviewer."


@pytest.fixture
def fake_reviewer():
    return FakeReviewer(
        model=TestModel(
            custom_output_args={
                "dimension": "fake_dimension",
                "outcome": "pass",
                "draft_hash": "x",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "reviewer_id": "fake_dimension@v1",
                "findings": [],
                "notes": "",
            }
        )
    )


def test_reviewer_agent_has_dimension_attribute():
    assert FakeReviewer.dimension == "fake_dimension"


@pytest.mark.asyncio
async def test_reviewer_agent_run_returns_reviewerverdict(tmp_path, fake_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")

    verdict = await fake_reviewer.run(
        draft=draft,
        spec_context={"behavior_name": "auth", "behavior_description": "log in"},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "fake_dimension"
    assert verdict.outcome in ("pass", "fail")
    assert verdict.reviewer_id == "fake_dimension@v1"


@pytest.mark.asyncio
async def test_reviewer_agent_run_persists_verdict(tmp_path, fake_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="x", gherkin_body="Given y")
    path = tmp_path / "v.yaml"

    await fake_reviewer.run(
        draft=draft, spec_context={}, mapping=mapping, events_log=log, verdict_path=path
    )
    assert path.exists()
    events = log.read_all()
    assert any(e.event_type.value == "reviewer_verdict_recorded" for e in events)


def test_reviewer_agent_requires_dimension():
    class BrokenReviewer(ReviewerAgent):
        def _system_prompt(self) -> str:
            return "x"

    with pytest.raises(ValueError, match="dimension"):
        BrokenReviewer(model=TestModel())
