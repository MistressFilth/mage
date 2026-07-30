"""Integration tests for InscribeStage (skeleton)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.orchestration.inscribe import InscribeStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig
from mage.verification.reviewers.determinism import DeterminismReviewer
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
from mage.verification.reviewers.step_grammar import StepGrammarReviewer
from mage.verification.reviewers.testability import TestabilityReviewer


@pytest.fixture(autouse=True)
def use_test_model():
    """Force Pydantic-AI agents to use TestModel for deterministic tests."""
    models.ALLOW_MODEL_REQUESTS = False
    yield


@pytest.fixture
def all_seven_reviewers():
    """All 7 reviewers with TestModel + canned ReviewerVerdict (pass)."""
    now = datetime.now(UTC)
    canned_args = {
        "dimension": "PLACEHOLDER",
        "outcome": "pass",
        "draft_hash": "x",
        "reviewed_at": now.isoformat(),
        "reviewer_id": "PLACEHOLDER@v1",
        "findings": [],
        "notes": "",
    }

    def _reviewer(reviewer_cls, dimension):
        return reviewer_cls(
            model=TestModel(
                custom_output_args={
                    **canned_args,
                    "dimension": dimension,
                    "reviewer_id": f"{dimension}@v1",
                }
            )
        )

    return [
        _reviewer(SpecComplianceReviewer, "spec_compliance"),
        _reviewer(ScenarioClarityReviewer, "scenario_clarity"),
        _reviewer(StepGrammarReviewer, "step_grammar"),
        _reviewer(TestabilityReviewer, "testability"),
        _reviewer(DeterminismReviewer, "determinism"),
        _reviewer(NamingIdiomReviewer, "naming_idiom"),
        _reviewer(LifecycleTagsReviewer, "lifecycle_tags"),
    ]


@pytest.fixture
def canned_inscribe_output() -> InscribeOutput:
    """Concrete output that the InscribeAgent TestModel will return."""
    return InscribeOutput(
        scenarios=[
            ScenarioSpec(
                name="login succeeds",
                gherkin_body=(
                    "Given a user with valid credentials\n"
                    "When they attempt to log in\n"
                    "Then they are authenticated"
                ),
            ),
        ]
    )


def _write_behaviors_yaml(project_dir: Path, feature_id: str = "feat-1") -> Path:
    path = project_dir / "behaviors.yaml"
    path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": feature_id,
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [
            {
                "id": "00000",
                "name": "authenticate-user",
                "description": "User logs in",
                "depends_on": [],
                "notes": "",
                "cross_behavior_links": [],
            },
        ],
    }))
    return path


@pytest.mark.asyncio
async def test_inscribe_stage_runs_end_to_end_with_test_model(
    tmp_path, all_seven_reviewers, canned_inscribe_output
):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    events_path = project_dir / "events.jsonl"
    log = EventsLog(events_path)
    _write_behaviors_yaml(project_dir)

    mapping = MappingArtifact(
        project_id="test-proj",
        base_bids=[{
            "base_bid": "00000",
            "behavior_name": "authenticate-user",
            "behavior_description": "User logs in",
            "depends_on": [],
            "notes": "",
            "scenarios": [],
            "reversion_log": [],
            "post_live_revisions": [],
            "cross_behavior_links": [],
        }],
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    host_config = HostConfig(max_iterations=3)
    inscribe_agent = InscribeAgent(
        model=TestModel(custom_output_args=canned_inscribe_output)
    )

    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=all_seven_reviewers,
    )

    new_context = await stage.run(context)
    assert new_context is not None
    # At least the Inscribe events should be in the log
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "inscribe_started" in event_types
    assert "inscribe_completed" in event_types
    assert "scenario_approved" in event_types


@pytest.mark.asyncio
async def test_inscribe_stage_halts_when_budget_exhausted(tmp_path, monkeypatch):
    """When iteration >= max_iterations and aggregate says needs_refactor,
    emit REVIEW_HALT_PERSISTED and raise ReviewBudgetExhausted."""
    from mage.orchestration.inscribe import InscribeStage, ReviewBudgetExhausted
    from mage.agents.inscribe import InscribeAgent, ScenarioSpec, InscribeOutput

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": "f",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [{
            "id": "00000", "name": "authenticate-user",
            "description": "User logs in", "depends_on": [],
            "notes": "", "cross_behavior_links": [],
        }],
    }))

    mapping = MappingArtifact(
        project_id="p",
        base_bids=[{
            "base_bid": "00000", "behavior_name": "authenticate-user",
            "behavior_description": "User logs in", "depends_on": [],
            "notes": "", "scenarios": [], "reversion_log": [],
            "post_live_revisions": [], "cross_behavior_links": [],
        }],
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    # Force InscribeAgent to draft a scenario
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=None))

    # Reviewers that always fail (we'll use TestModel that returns fail verdicts
    # via custom_output_args)
    from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
    from mage.artifacts.verdict import ReviewerVerdict
    from datetime import datetime, UTC

    class AlwaysFailReviewer(SpecComplianceReviewer):
        async def run(self, *, draft, spec_context, mapping, events_log, verdict_path):
            v = ReviewerVerdict(
                dimension=self.dimension, outcome="fail", draft_hash="x",
                reviewed_at=datetime.now(UTC), reviewer_id=f"{self.dimension}@v1",
                findings=[],
            )
            from mage.artifacts.verdict import VerdictArtifact
            await VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    failing_reviewer = AlwaysFailReviewer(model=TestModel(custom_output_args=None))

    host_config = HostConfig(max_iterations=2)  # small budget
    stage = InscribeStage(
        events_log=log, agent=inscribe_agent, host_config=host_config,
        reviewers=[failing_reviewer],
    )

    with pytest.raises(ReviewBudgetExhausted):
        await stage.run(context)

    # Halt event was emitted
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "review_halt_persisted" in event_types
