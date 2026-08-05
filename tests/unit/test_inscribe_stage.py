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
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
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
            }
        )
    )
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
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
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
    from mage.agents.inscribe import InscribeAgent
    from mage.orchestration.inscribe import InscribeStage, ReviewBudgetExhausted

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": "f",
                "enumerated_at": "2026-07-27T00:00:00Z",
                "behaviors": [
                    {
                        "id": "00000",
                        "name": "authenticate-user",
                        "description": "User logs in",
                        "depends_on": [],
                        "notes": "",
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )

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
            }
        ],
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
    )

    # Force InscribeAgent to draft a scenario
    inscribe_agent = InscribeAgent(model=TestModel(custom_output_args=None))

    # Reviewers that always fail (we'll use TestModel that returns fail verdicts
    # via custom_output_args)
    from datetime import UTC, datetime

    from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer

    class AlwaysFailReviewer(SpecComplianceReviewer):
        async def run(
            self, *, draft, spec_context, mapping, events_log, verdict_path, **kwargs
        ):
            v = ReviewerVerdict(
                dimension=self.dimension,
                outcome="fail",
                draft_hash="x",
                reviewed_at=datetime.now(UTC),
                reviewer_id=f"{self.dimension}@v1",
                findings=[],
            )
            from mage.artifacts.verdict import VerdictArtifact

            await VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    failing_reviewer = AlwaysFailReviewer(model=TestModel(custom_output_args=None))

    host_config = HostConfig(max_iterations=2)  # small budget
    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=[failing_reviewer],
    )

    with pytest.raises(ReviewBudgetExhausted) as exc_info:
        await stage.run(context)

    # Halt event was emitted
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "review_halt_persisted" in event_types

    # Plan 25: halt semantics — a single-scenario behavior halts with one
    # halted_sub_bid (the derived sub_bid for the only scenario).
    halt_events = [e for e in events if e.event_type.value == "review_halt_persisted"]
    assert len(halt_events) == 1
    assert "halted_sub_bids" in halt_events[0].payload
    assert len(halt_events[0].payload["halted_sub_bids"]) == 1

    assert exc_info.value.halted_sub_bids == halt_events[0].payload["halted_sub_bids"]


@pytest.mark.asyncio
async def test_per_scenario_halt_sibling_continues(tmp_path) -> None:
    """I5 fix: when one scenario exhausts, sibling scenarios continue drafting
    and the behavior-level halt carries the halted sub_bid list."""
    from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
    from mage.orchestration.inscribe import InscribeStage, ReviewBudgetExhausted
    from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": "f",
                "enumerated_at": "2026-07-27T00:00:00Z",
                "behaviors": [
                    {
                        "id": "00000",
                        "name": "authenticate-user",
                        "description": "User logs in",
                        "depends_on": [],
                        "notes": "",
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )

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
            }
        ],
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
    )

    class TwoScenarioAgent(InscribeAgent):
        async def run(self, *, behavior, existing_scenarios, mapping, **_):
            return InscribeOutput(
                scenarios=[
                    ScenarioSpec(
                        name="first-scenario",
                        gherkin_body="Scenario: first-scenario\n  Given x\n",
                        tags=[],
                    ),
                    ScenarioSpec(
                        name="second-scenario",
                        gherkin_body="Scenario: second-scenario\n  Given y\n",
                        tags=[],
                    ),
                ],
            )

    class AlwaysFailReviewer(SpecComplianceReviewer):
        async def run(
            self, *, draft, spec_context, mapping, events_log, verdict_path, **_
        ):
            v = ReviewerVerdict(
                dimension=self.dimension,
                outcome="fail",
                draft_hash="x",
                reviewed_at=datetime.now(UTC),
                reviewer_id=f"{self.dimension}@v1",
                findings=[],
            )
            from mage.artifacts.verdict import VerdictArtifact

            await VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    host_config = HostConfig(max_iterations=1)
    stage = InscribeStage(
        events_log=log,
        agent=TwoScenarioAgent(model=TestModel(custom_output_args=None)),
        host_config=host_config,
        reviewers=[AlwaysFailReviewer(model=TestModel(custom_output_args=None))],
    )

    with pytest.raises(ReviewBudgetExhausted) as exc_info:
        await stage.run(context)

    events = log.read_all()

    # Per-scenario emissions: both scenarios draft, both fail review, both halt.
    # With max_iterations=1, each scenario emits one SCENARIO_HALT_PERSISTED
    # for the needs_refactor outcome and one for the iteration budget halt
    # check — 2 events per scenario, 4 total.
    halt_events = [e for e in events if e.event_type.value == "scenario_halt_persisted"]
    assert len(halt_events) == 4
    halted_sub_bids = {e.payload["sub_bid"] for e in halt_events}
    assert len(halted_sub_bids) == 2

    # Per-behavior event: one REVIEW_HALT_PERSISTED with the full halted set.
    behavior_halt = [e for e in events if e.event_type.value == "review_halt_persisted"]
    assert len(behavior_halt) == 1
    assert set(behavior_halt[0].payload["halted_sub_bids"]) == halted_sub_bids

    # Exception carries the halted set.
    assert set(exc_info.value.halted_sub_bids) == halted_sub_bids


@pytest.mark.asyncio
async def test_review_budget_exhausted_has_halted_sub_bids_attribute() -> None:
    """ReviewBudgetExhausted exposes halted_sub_bids as a public attribute."""
    from mage.orchestration.inscribe import ReviewBudgetExhausted

    exc = ReviewBudgetExhausted(
        base_bid="00000",
        scenario_name="authenticate-user",
        iteration=2,
        halted_sub_bids=["00000-0", "00000-1"],
    )
    assert exc.halted_sub_bids == ["00000-0", "00000-1"]
    assert exc.base_bid == "00000"
    assert exc.scenario_name == "authenticate-user"
    assert exc.iteration == 2


@pytest.mark.asyncio
async def test_existing_scenarios_uses_scenario_name_and_gherkin(
    tmp_path, monkeypatch
) -> None:
    """I2 fix: existing_scenarios reflects real scenario_name + gherkin_body
    on prior ScenarioEntry, not the sub_bid placeholder."""
    from mage.agents.inscribe import InscribeAgent
    from mage.artifacts.mapping import LifecycleStatus, ScenarioEntry
    from mage.orchestration.events import EventsLog
    from mage.orchestration.inscribe import InscribeStage

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": "f",
                "enumerated_at": "2026-07-27T00:00:00Z",
                "behaviors": [
                    {
                        "id": "00000",
                        "name": "authenticate-user",
                        "description": "User logs in",
                        "depends_on": [],
                        "notes": "",
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )

    prior = ScenarioEntry(
        sub_bid="00000-0",
        scenario_name="login-with-creds",
        gherkin_body="Scenario: login-with-creds\n  Given a user\n  When they log in\n",
        scenario_text_hash="deadbeef",
        lifecycle_status=LifecycleStatus.APPROVED,
    )

    mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            {
                "base_bid": "00000",
                "behavior_name": "authenticate-user",
                "behavior_description": "User logs in",
                "depends_on": [],
                "notes": "",
                "scenarios": [prior.model_dump()],
                "reversion_log": [],
                "post_live_revisions": [],
                "cross_behavior_links": [],
            }
        ],
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
    )

    captured: dict = {}

    class CaptureAgent(InscribeAgent):
        async def run(self, *, behavior, existing_scenarios, mapping, **_):
            captured["existing_scenarios"] = existing_scenarios
            from mage.agents.inscribe import InscribeOutput

            return InscribeOutput(scenarios=[])

    host_config = HostConfig(max_iterations=1)
    stage = InscribeStage(
        events_log=log,
        agent=CaptureAgent(model=TestModel(custom_output_args=None)),
        host_config=host_config,
        reviewers=[],
    )
    await stage.run(context)

    assert captured["existing_scenarios"] == [
        {
            "name": "login-with-creds",
            "gherkin_body": "Scenario: login-with-creds\n  Given a user\n  When they log in\n",
        }
    ]


@pytest.mark.asyncio
async def test_existing_scenarios_falls_back_to_empty_for_old_data(
    tmp_path,
) -> None:
    """Pre-migration ScenarioEntry with no scenario_name/gherkin_body —
    the agent receives empty strings, not the sub_bid placeholder."""
    from mage.agents.inscribe import InscribeAgent
    from mage.orchestration.events import EventsLog
    from mage.orchestration.inscribe import InscribeStage

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    log = EventsLog(project_dir / "events.jsonl")
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": "f",
                "enumerated_at": "2026-07-27T00:00:00Z",
                "behaviors": [
                    {
                        "id": "00000",
                        "name": "authenticate-user",
                        "description": "User logs in",
                        "depends_on": [],
                        "notes": "",
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )

    # Pre-migration shape: only the legacy fields.
    mapping = MappingArtifact.model_validate(
        {
            "project_id": "p",
            "base_bids": [
                {
                    "base_bid": "00000",
                    "behavior_name": "authenticate-user",
                    "behavior_description": "User logs in",
                    "depends_on": [],
                    "notes": "",
                    "scenarios": [
                        {
                            "sub_bid": "00000-0",
                            "scenario_text_hash": "deadbeef",
                            "lifecycle_status": "approved",
                        }
                    ],
                    "reversion_log": [],
                    "post_live_revisions": [],
                    "cross_behavior_links": [],
                }
            ],
        }
    )
    await mapping.save(project_dir / "mapping.yaml")

    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
    )

    captured: dict = {}

    class CaptureAgent(InscribeAgent):
        async def run(self, *, behavior, existing_scenarios, mapping, **_):
            captured["existing_scenarios"] = existing_scenarios
            from mage.agents.inscribe import InscribeOutput

            return InscribeOutput(scenarios=[])

    host_config = HostConfig(max_iterations=1)
    stage = InscribeStage(
        events_log=log,
        agent=CaptureAgent(model=TestModel(custom_output_args=None)),
        host_config=host_config,
        reviewers=[],
    )
    await stage.run(context)

    assert captured["existing_scenarios"] == [{"name": "", "gherkin_body": ""}]
