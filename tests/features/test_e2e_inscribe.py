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


@pytest.mark.asyncio
async def test_e2e_inscribe_happy_path(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    events_path = project_dir / "events.jsonl"
    log = EventsLog(events_path)

    # Write behaviors.yaml
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": "feat-auth",
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

    # Write mapping.yaml
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
        model=TestModel(custom_output_args=_canned_inscribe_output())
    )
    reviewers = _all_seven_reviewers()

    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=reviewers,
    )

    await stage.run(context)

    # Verify mapping has at least one APPROVED scenario under base_bid 00000
    updated_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    target = next(e for e in updated_mapping.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) >= 1
    assert target.scenarios[0].lifecycle_status == LifecycleStatus.APPROVED

    # Verify scenario .feature file was written
    scenario_files = list((project_dir / "scenarios" / "00000").glob("*.feature"))
    assert len(scenario_files) >= 1

    # Verify verdict files were written
    verdicts_root = project_dir / ".mage" / "verdicts"
    assert verdicts_root.exists()

    # Verify events
    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "inscribe_started" in event_types
    assert "inscribe_completed" in event_types
    assert "scenario_approved" in event_types


@pytest.mark.asyncio
async def test_e2e_inscribe_with_subset_of_reviewers(tmp_path: Path) -> None:
    """When HostConfig.enabled_reviewers is a subset, only those run."""
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

    # enabled_reviewers subset (only 3 of 7)
    reviewers = [
        _make_reviewer(SpecComplianceReviewer, "spec_compliance"),
        _make_reviewer(TestabilityReviewer, "testability"),
        _make_reviewer(LifecycleTagsReviewer, "lifecycle_tags"),
    ]
    host_config = HostConfig(
        max_iterations=3,
        enabled_reviewers=["spec_compliance", "testability", "lifecycle_tags"],
    )

    stage = InscribeStage(
        events_log=log,
        agent=InscribeAgent(
            model=TestModel(custom_output_args=_canned_inscribe_output())
        ),
        host_config=host_config,
        reviewers=reviewers,
    )
    await stage.run(context)

    # Mapping was updated with at least one approved scenario
    updated_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    target = next(e for e in updated_mapping.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) >= 1


@pytest.mark.asyncio
async def test_e2e_inscribe_halts_on_budget_exhaustion(tmp_path: Path) -> None:
    """When reviewers always fail and budget is small, Inscribe halts."""
    from datetime import UTC, datetime

    from mage.artifacts.verdict import ReviewerVerdict, VerdictArtifact
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
            await VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    failing_reviewer = AlwaysFailReviewer(model=TestModel(custom_output_args=None))
    host_config = HostConfig(max_iterations=2)

    stage = InscribeStage(
        events_log=log,
        agent=InscribeAgent(
            model=TestModel(custom_output_args=_canned_inscribe_output())
        ),
        host_config=host_config,
        reviewers=[failing_reviewer],
    )

    with pytest.raises(ReviewBudgetExhausted) as exc_info:
        await stage.run(context)
    assert exc_info.value.halted_sub_bids  # non-empty
    assert all(isinstance(b, str) for b in exc_info.value.halted_sub_bids)

    events = log.read_all()
    event_types = {e.event_type.value for e in events}
    assert "review_halt_persisted" in event_types
    halt_events = [e for e in events if e.event_type.value == "review_halt_persisted"]
    assert set(exc_info.value.halted_sub_bids) == set(
        halt_events[0].payload["halted_sub_bids"]
    )


@pytest.mark.asyncio
async def test_e2e_inscribe_emits_mechanical_precheck_passed(tmp_path: Path) -> None:
    """With the default empty-check MechanicalVerifier, every scenario
    passes pre-check and emits MECHANICAL_PRECHECK_PASSED before the
    reviewer loop runs."""
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

    host_config = HostConfig(max_iterations=3)
    inscribe_agent = InscribeAgent(
        model=TestModel(custom_output_args=_canned_inscribe_output())
    )
    # No mechanical verifier passed → default is empty checks → all pass.
    stage = InscribeStage(
        events_log=log,
        agent=inscribe_agent,
        host_config=host_config,
        reviewers=_all_seven_reviewers(),
    )

    await stage.run(context)

    events = log.read_all()
    precheck_passed = [
        e for e in events if e.event_type.value == "mechanical_precheck_passed"
    ]
    assert len(precheck_passed) >= 1
    # The first PRECHECK_PASSED comes before any REVIEWER_VERDICT_RECORDED.
    first_precheck = precheck_passed[0]
    first_reviewer_verdict = next(
        (e for e in events if e.event_type.value == "reviewer_verdict_recorded"),
        None,
    )
    assert first_reviewer_verdict is not None
    assert first_precheck.timestamp < first_reviewer_verdict.timestamp


@pytest.mark.asyncio
async def test_e2e_per_scenario_halt_resume(tmp_path: Path) -> None:
    """End-to-end halt + resume for Plan 25.

    Behavior: scenario-B is already APPROVED on disk (simulates a feature
    resumed mid-build). scenario-A is new.

    First run: scenario-A fails review and exhausts its budget. The
    InscribeStage raises ReviewBudgetExhausted with halted_sub_bids set.
    The test then persists behavior_halt onto BaseBIDEntry (the action the
    PipelineGraph takes in production — see graph.py:104-126).

    Resume: the mapping is reloaded from disk. scenario-A re-drafts; the
    agent receives scenario-B's real scenario_name + gherkin_body in
    existing_scenarios (I2 fix). scenario-A then approves.

    Asserts:
    - halted_sub_bids is non-empty after the first run
    - behavior_halt on the reloaded BaseBIDEntry equals halted_sub_bids
    - scenario-B survives the halt intact (already APPROVED, never re-drafted)
    - existing_scenarios on resume carries scenario-B's real name + body
    - scenario-A approves on resume; final mapping has both approved
    """
    from mage.artifacts.mapping import ScenarioEntry
    from mage.artifacts.verdict import VerdictArtifact
    from mage.orchestration.inscribe import ReviewBudgetExhausted
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
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )

    prior_b_body = (
        "Scenario: scenario-B\n"
        "  Given a user\n"
        "  When they sign up\n"
        "  Then they are registered\n"
    )
    prior_b = ScenarioEntry(
        sub_bid="00000-1",
        scenario_name="scenario-B",
        gherkin_body=prior_b_body,
        scenario_text_hash="cafef00d",
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
                "scenarios": [prior_b.model_dump()],
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
            await VerdictArtifact.finalize(verdict_path, v, events_log)
            return v

    def _canned_scenario_a() -> InscribeOutput:
        return InscribeOutput(
            scenarios=[
                ScenarioSpec(
                    name="scenario-A",
                    gherkin_body=(
                        "Scenario: scenario-A\n"
                        "  Given a user\n"
                        "  When they log in\n"
                        "  Then they are authenticated\n"
                    ),
                ),
            ]
        )

    captured: dict = {}

    class DraftingAgent(InscribeAgent):
        """Capture `existing_scenarios` on each run for the I2 assertion.

        The parent's prompt-formatter no longer relies on attribute access
        (it uses ``.get('name', '')``), so bypassing it is unnecessary for
        that reason. The override remains solely to record the
        ``existing_scenarios`` payload the stage passes in, so the test can
        assert that scenario-B's real ``name`` + ``gherkin_body`` reach the
        agent on resume.
        """

        async def run(self, *, behavior, existing_scenarios, mapping, **_):
            captured.setdefault("calls", []).append(list(existing_scenarios))
            return _canned_scenario_a()

    # First run: scenario-A fails review with max_iterations=1 → halt.
    failing_reviewer = AlwaysFailReviewer(model=TestModel(custom_output_args=None))
    first_stage = InscribeStage(
        events_log=log,
        agent=DraftingAgent(model=TestModel(custom_output_args=_canned_scenario_a())),
        host_config=HostConfig(max_iterations=1),
        reviewers=[failing_reviewer],
    )

    with pytest.raises(ReviewBudgetExhausted) as exc_info:
        await first_stage.run(context)
    assert exc_info.value.halted_sub_bids
    assert all(isinstance(b, str) for b in exc_info.value.halted_sub_bids)

    first_events = log.read_all()
    halt_event_types = {e.event_type.value for e in first_events}
    assert "scenario_halt_persisted" in halt_event_types
    assert "review_halt_persisted" in halt_event_types

    # Simulate the graph layer: persist behavior_halt onto BaseBIDEntry.
    halted = sorted(exc_info.value.halted_sub_bids)
    target = next(e for e in context.mapping.base_bids if e.base_bid == "00000")
    updated_target = target.model_copy(update={"behavior_halt": halted})
    persisted_mapping = context.mapping.model_copy(
        update={
            "base_bids": [
                updated_target if b.base_bid == "00000" else b
                for b in context.mapping.base_bids
            ]
        }
    )
    await persisted_mapping.save(project_dir / "mapping.yaml")

    # Reload from disk — behavior_halt must be non-empty after the first run.
    reloaded = MappingArtifact.load(project_dir / "mapping.yaml")
    reloaded_target = next(e for e in reloaded.base_bids if e.base_bid == "00000")
    assert reloaded_target.behavior_halt == halted
    # scenario-B survives the halt intact (it was already APPROVED and
    # the agent was told to draft only scenario-A).
    surviving_names = {s.scenario_name for s in reloaded_target.scenarios}
    assert surviving_names == {"scenario-B"}
    assert all(
        s.lifecycle_status == LifecycleStatus.APPROVED
        for s in reloaded_target.scenarios
    )

    # Second run: passing reviewers, scenario-A re-drafts.
    captured.clear()
    second_context = PipelineContext(
        project_dir=project_dir,
        mapping=reloaded,
        events_log=log,
        plan_path=project_dir / "plan.md",
    )
    second_stage = InscribeStage(
        events_log=log,
        agent=DraftingAgent(model=TestModel(custom_output_args=_canned_scenario_a())),
        host_config=HostConfig(max_iterations=3),
        reviewers=_all_seven_reviewers(),
    )
    await second_stage.run(second_context)

    # I2 fix end-to-end: the agent saw scenario-B's real name + body on
    # resume, not the sub_bid placeholder. Find the call where scenario-A
    # is drafted; that call is the first one (existing_scenarios reflects
    # the state at draft time, pre-approval).
    draft_calls = captured["calls"]
    assert draft_calls, "agent was not invoked on resume"
    saw_existing = any(
        call == [{"name": "scenario-B", "gherkin_body": prior_b_body}]
        for call in draft_calls
    )
    assert saw_existing, (
        f"expected scenario-B's real name+body in existing_scenarios; "
        f"got calls={draft_calls}"
    )

    # Final mapping on disk: both scenarios approved.
    final_mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    final_target = next(e for e in final_mapping.base_bids if e.base_bid == "00000")
    final_names = {s.scenario_name for s in final_target.scenarios}
    assert len(final_target.scenarios) == 2
    assert final_names == {"scenario-A", "scenario-B"}
    assert all(
        s.lifecycle_status == LifecycleStatus.APPROVED for s in final_target.scenarios
    )
