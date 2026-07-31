"""InscribeStage reviewer dispatch uses asyncio.Semaphore sized by host_config.max_concurrent_llm_calls."""

from __future__ import annotations

import asyncio
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


def _write_behaviors_yaml(project_dir: Path) -> None:
    (project_dir / "behaviors.yaml").write_text(
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


@pytest.mark.asyncio
async def test_inscribe_stage_constructs_semaphore_with_max_concurrent_llm_calls(
    tmp_path, monkeypatch
):
    """The reviewer loop must dispatch concurrently via asyncio.Semaphore
    sized by host_config.max_concurrent_llm_calls."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    _write_behaviors_yaml(project_dir)

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
    )

    # Record every asyncio.Semaphore construction call without breaking it.
    semaphore_calls: list[int] = []
    real_semaphore = asyncio.Semaphore

    def recording_semaphore(value=1, *args, **kwargs):
        semaphore_calls.append(value)
        return real_semaphore(value, *args, **kwargs)

    monkeypatch.setattr(asyncio, "Semaphore", recording_semaphore)

    host_config = HostConfig(
        max_iterations=3,
        max_concurrent_llm_calls=3,
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

    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=_all_seven_reviewers(),
    )

    await stage.run(context)

    reviewer_loop_calls = [v for v in semaphore_calls if v == 3]
    assert reviewer_loop_calls, (
        f"Expected asyncio.Semaphore(3) for max_concurrent_llm_calls=3, "
        f"got calls: {semaphore_calls}"
    )
