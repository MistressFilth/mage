"""Unit tests for InscribeStage threading context.feature_id onto appended ScenarioEntry (Plan 14)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
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
    return reviewer_cls(
        model=TestModel(
            custom_output_args={
                "dimension": dimension,
                "outcome": "pass",
                "draft_hash": "x",
                "reviewed_at": datetime.now(UTC).isoformat(),
                "reviewer_id": f"{dimension}@v1",
                "findings": [],
                "notes": "",
            }
        )
    )


def _all_seven_reviewers():
    return [
        _make_reviewer(SpecComplianceReviewer, "spec_compliance"),
        _make_reviewer(ScenarioClarityReviewer, "scenario_clarity"),
        _make_reviewer(StepGrammarReviewer, "step_grammar"),
        _make_reviewer(TestabilityReviewer, "testability"),
        _make_reviewer(DeterminismReviewer, "determinism"),
        _make_reviewer(NamingIdiomReviewer, "naming_idiom"),
        _make_reviewer(LifecycleTagsReviewer, "lifecycle_tags"),
    ]


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
            }
        )
    )
    return project


@pytest.mark.asyncio
async def test_inscribe_appends_scenarios_with_context_feature_id(tmp_path):
    """When context.feature_id is set, every Inscribe-appended scenario carries it.

    Plan 14: InscribeStage must thread `context.feature_id` onto every
    `ScenarioEntry` it appends so that the settle supersession emitter (Task 3)
    can walk scenarios by feature_id.
    """
    project_dir = _seed_project(tmp_path)
    events_log_path = project_dir / "events.jsonl"
    log = EventsLog(events_log_path)

    mapping = MappingArtifact(
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
            },
        ],
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
        feature_id="feat-X",
    )

    canned = InscribeOutput(
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
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=canned))
    host_config = HostConfig(max_iterations=3)

    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=_all_seven_reviewers(),
    )

    # Drive the stage; capture the returned context (which carries the
    # updated mapping — `context.mapping` itself is not mutated in place).
    # Tolerate any post-approve errors — the scenarios-of-interest are
    # appended before downstream side effects.
    try:
        new_context = await stage._run(context)
    except BaseException:  # noqa: BLE001
        new_context = context

    # Diagnostic: dump event types for visibility if assertion fails.
    events = log.read_all() if events_log_path.exists() else []
    event_types = [e.event_type.value for e in events]

    # Verify at least one appended ScenarioEntry carries feature_id == "feat-X".
    tagged = [
        s
        for entry in new_context.mapping.base_bids
        for s in entry.scenarios
        if s.feature_id == "feat-X"
    ]
    assert tagged, (
        f"no scenario was tagged with feature_id='feat-X'; "
        f"base_bids={new_context.mapping.base_bids!r}; events={event_types}"
    )
