"""End-to-end Inscribe test: Decomposition outputs → Inscribe → APPROVED mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
from mage.artifacts.mapping import LifecycleStatus, MappingArtifact
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


def _make_reviewer(reviewer_cls, dimension: str):
    """Build a reviewer with a canned pass ReviewerVerdict for TestModel.

    Avoids the datetime validation failure that occurs when TestModel emits
    string placeholders ("...") for datetime fields.
    """
    canned = ReviewerVerdict(
        dimension=dimension,
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id=f"{dimension}@v1",
        findings=[],
        notes="",
    )
    return reviewer_cls(model=TestModel(custom_output_args=canned))


def _all_seven_reviewers() -> list:
    """All 7 reviewers with TestModel + canned pass ReviewerVerdict."""
    return [
        _make_reviewer(SpecComplianceReviewer, "spec_compliance"),
        _make_reviewer(ScenarioClarityReviewer, "scenario_clarity"),
        _make_reviewer(StepGrammarReviewer, "step_grammar"),
        _make_reviewer(TestabilityReviewer, "testability"),
        _make_reviewer(DeterminismReviewer, "determinism"),
        _make_reviewer(NamingIdiomReviewer, "naming_idiom"),
        _make_reviewer(LifecycleTagsReviewer, "lifecycle_tags"),
    ]


def _canned_inscribe_output() -> InscribeOutput:
    """Concrete output the InscribeAgent TestModel will return."""
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


def test_e2e_inscribe_happy_path(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    events_path = project_dir / "events.jsonl"
    log = EventsLog(events_path)

    # Write behaviors.yaml
    (project_dir / "behaviors.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "feature_id": "feat-auth",
        "enumerated_at": "2026-07-27T00:00:00Z",
        "behaviors": [{
            "id": "00000",
            "name": "authenticate-user",
            "description": "User logs in with email and password",
            "depends_on": [],
            "notes": "",
            "cross_behavior_links": [],
        }],
    }))

    # Write mapping.yaml
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
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir, mapping=mapping, events_log=log,
        plan_path=project_dir / "plan.md",
    )

    host_config = HostConfig(max_iterations=3)
    inscribe_agent = InscribeAgent(
        model=TestModel(custom_output_args=_canned_inscribe_output())
    )
    reviewers = _all_seven_reviewers()

    stage = InscribeStage(
        events_log=log, agent=inscribe_agent, host_config=host_config,
        reviewers=reviewers,
    )

    new_context = stage.run(context)

    # Verify mapping has at least one APPROVED scenario under base_bid 00000
    updated_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    target = next(e for e in updated_mapping.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) >= 1
    assert target.scenarios[0].lifecycle_status == LifecycleStatus.APPROVED

    # Verify scenario .feature file was written
    scenario_files = list((project_dir / "scenarios" / "00000").glob("*.feature"))
    assert len(scenario_files) >= 1

    # Verify verdict files were written
    verdicts_root = project_dir / ".haileris" / "verdicts"
    assert verdicts_root.exists()

    # Verify events
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "inscribe_started" in event_types
    assert "inscribe_completed" in event_types
    assert "scenario_approved" in event_types
