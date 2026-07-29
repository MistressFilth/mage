"""End-to-end revision full-loop test.

Plan 7, Task 15. Exercises the Three Practices P5 rule (`begin_revision`)
through the real Inscribe pipeline:

1. Build a project with one scenario mapped.
2. Run ``InscribeStage.run(context)`` to reach ``SCENARIO_APPROVED``.
3. Call ``policy.begin_revision`` directly to simulate a spec-route finding.
4. Verify scenario ``lifecycle_status == INSCRIBING`` and the
   ``BaseBIDEntry``'s ``reversion_log`` has one entry.
5. Re-run ``InscribeStage.run(context)`` from scratch (clearing the
   previously-approved scenario, per "restart Inscribe from scratch" spec
   semantics) and verify the scenario reaches ``APPROVED`` again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
)
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.discipline.policy import begin_revision
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


def test_e2e_revision_full_loop(tmp_path: Path) -> None:
    """Full revision loop: APPROVED → begin_revision → INSCRIBING → APPROVED.

    Mirrors what the Inspect-loop spec-route finding would trigger, but
    calls ``policy.begin_revision`` directly so the test stays focused on
    the discipline policy contract rather than the inspect mechanism.
    """
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")

    # Write behaviors.yaml
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "feature_id": "f",
                "enumerated_at": "2026-07-27T00:00:00Z",
                "behaviors": [
                    {
                        "id": "00000",
                        "name": "authenticate-user",
                        "description": "User logs in with email and password",
                        "depends_on": [],
                        "notes": "",
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )

    # Write mapping.yaml with one empty-scenario BaseBIDEntry.
    mapping = MappingArtifact(
        project_id="test-proj",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="authenticate-user",
                behavior_description="User logs in",
                depends_on=[],
                notes="",
                scenarios=[],
                reversion_log=[],
                post_live_revisions=[],
                cross_behavior_links=[],
            ),
        ],
    )
    mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
    )

    host_config = HostConfig(max_iterations=3)
    inscribe_agent = InscribeAgent(
        model=TestModel(custom_output_args=_canned_inscribe_output())
    )
    reviewers = _all_seven_reviewers()

    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=reviewers,
    )

    # Step 1: Run Inscribe to APPROVED.
    new_context = stage.run(context)

    updated = MappingArtifact.load(project_dir / "mapping.yaml")
    target_entry = next(e for e in updated.base_bids if e.base_bid == "00000")
    assert len(target_entry.scenarios) == 1
    first_scenario = target_entry.scenarios[0]
    sub_bid = first_scenario.sub_bid
    assert first_scenario.lifecycle_status == LifecycleStatus.APPROVED

    # Step 2: Call begin_revision directly (simulating inspect-loop
    # spec-route finding).
    revised = begin_revision(
        mapping=updated,
        sub_bid=sub_bid,
        reason="spec ambiguity in step 2",
        originating_stage="inspect_loop",
        timestamp=datetime.now(UTC),
    )

    # Step 3: Verify the discipline policy mutated the entry.
    target_entry = next(e for e in revised.base_bids if e.base_bid == "00000")
    assert target_entry.scenarios[0].lifecycle_status == LifecycleStatus.INSCRIBING
    assert len(target_entry.reversion_log) == 1
    assert target_entry.reversion_log[0].sub_bid == sub_bid
    assert target_entry.reversion_log[0].reason == "spec ambiguity in step 2"
    assert target_entry.reversion_log[0].originating_stage == "inspect_loop"

    # Step 4: Restart Inscribe from scratch. The spec semantics for
    # revision are "restart Inscribe from scratch"; in practice this
    # means clearing the previously-approved scenario before re-running.
    # ``InscribeStage`` appends a new scenario each run rather than
    # revising an existing one in place, so we drop the existing
    # scenario (and its on-disk .feature file) and rebuild the entry
    # with no scenarios, preserving the new reversion_log.
    cleaned_entry = target_entry.model_copy(update={"scenarios": []})
    cleaned_base_bids = [
        cleaned_entry if e.base_bid == "00000" else e for e in revised.base_bids
    ]
    cleaned = revised.model_copy(update={"base_bids": cleaned_base_bids})
    cleaned.save(project_dir / "mapping.yaml")

    # Also drop the on-disk scenario file from the previous run so the
    # re-run is a clean fresh start.
    feature_path = project_dir / "scenarios" / "00000" / "login succeeds.feature"
    if feature_path.exists():
        feature_path.unlink()

    new_context = new_context.model_copy(update={"mapping": cleaned})

    # Step 5: Re-run Inscribe to re-approve.
    stage.run(new_context)

    # Step 6: Verify scenario reaches APPROVED again.
    final = MappingArtifact.load(project_dir / "mapping.yaml")
    target_entry = next(e for e in final.base_bids if e.base_bid == "00000")
    assert len(target_entry.scenarios) == 1
    assert target_entry.scenarios[0].lifecycle_status == LifecycleStatus.APPROVED
    # The reversion_log from begin_revision is preserved across the
    # restart — it records history, not lifecycle state.
    assert len(target_entry.reversion_log) == 1
    assert target_entry.reversion_log[0].sub_bid == sub_bid
