"""Tests for the spec_compliance reviewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer


@pytest.fixture
def spec_compliance_reviewer():
    canned = ReviewerVerdict(
        dimension="spec_compliance",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="spec_compliance@v1",
    )
    return SpecComplianceReviewer(model=TestModel(custom_output_args=canned))


def test_dimension_is_spec_compliance():
    assert SpecComplianceReviewer.dimension == "spec_compliance"


@pytest.mark.asyncio
async def test_run_emits_reviewerverdict(tmp_path, spec_compliance_reviewer):
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p", base_bids=[])
    draft = ScenarioSpec(name="login", gherkin_body="Given ...")

    verdict = await spec_compliance_reviewer.run(
        draft=draft,
        spec_context={"behavior_name": "auth", "behavior_description": "log in"},
        mapping=mapping,
        events_log=log,
        verdict_path=tmp_path / "v.yaml",
    )
    assert isinstance(verdict, ReviewerVerdict)
    assert verdict.dimension == "spec_compliance"
    assert verdict.outcome in ("pass", "fail")
