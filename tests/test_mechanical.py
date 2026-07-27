"""Tests for mechanical author verification."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from haileris_v2.artifacts.bid import Base85BID
from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.verification.mechanical import (
    CheckResult,
    MechanicalCheck,
    MechanicalVerifier,
    ScenarioDraft,
    StepDefinitionsResolvableCheck,
)
from haileris_v2.verification.mechanical import GherkinSyntaxCheck
from haileris_v2.verification.mechanical import ScenarioNameUniqueCheck
from haileris_v2.verification.mechanical import TagsRegisteredCheck


class DummyCheck(MechanicalCheck):
    """A check that always passes."""

    name = "dummy_pass"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        return CheckResult(name=self.name, outcome="pass", detail=None)


class DummyFailingCheck(MechanicalCheck):
    """A check that always fails."""

    name = "dummy_fail"

    def _run(self, draft: ScenarioDraft, mapping: MappingArtifact) -> CheckResult:
        return CheckResult(name=self.name, outcome="fail", detail="intentional failure")


class TestMechanicalCheck:
    def test_subclass_must_implement_run(self, tmp_project_dir: Path):
        class Incomplete(MechanicalCheck):
            name = "incomplete"

        with pytest.raises(TypeError, match="abstract"):
            Incomplete()


class TestMechanicalVerifier:
    def test_empty_check_set(self, tmp_project_dir: Path):
        verifier = MechanicalVerifier(checks=[])
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test scenario",
            gherkin_text="Given x\nWhen y\nThen z",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x", "When y", "Then z"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        results = verifier.verify(draft, mapping)
        assert results == []

    def test_all_passing_checks(self, tmp_project_dir: Path):
        verifier = MechanicalVerifier(checks=[DummyCheck(), DummyCheck()])
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        results = verifier.verify(draft, mapping)
        assert all(r.outcome == "pass" for r in results)
        assert len(results) == 2

    def test_mixed_pass_fail(self, tmp_project_dir: Path):
        verifier = MechanicalVerifier(
            checks=[DummyCheck(), DummyFailingCheck(), DummyCheck()]
        )
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        results = verifier.verify(draft, mapping)
        assert len(results) == 3
        outcomes = [r.outcome for r in results]
        assert outcomes == ["pass", "fail", "pass"]


class TestGherkinSyntaxCheck:
    def test_valid_gherkin_passes(self, tmp_project_dir: Path):
        check = GherkinSyntaxCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nWhen an action\nThen a result",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "When an action", "Then a result"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_missing_when_fails(self, tmp_project_dir: Path):
        check = GherkinSyntaxCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nThen a result",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "Then a result"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "When" in (result.detail or "")

    def test_no_steps_fails(self, tmp_project_dir: Path):
        check = GherkinSyntaxCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=[],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"


class TestScenarioNameUniqueCheck:
    def test_unique_name_passes(self, tmp_project_dir: Path):
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: First\n    Given x\n\n  Scenario: Second\n    Given y\n"
        )
        check = ScenarioNameUniqueCheck()
        draft = ScenarioDraft(
            feature_path=feature_path,
            scenario_name="First",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_duplicate_name_fails(self, tmp_project_dir: Path):
        feature_path = tmp_project_dir / "test.feature"
        feature_path.write_text(
            "Feature: Test\n\n  Scenario: Same\n    Given x\n\n  Scenario: Same\n    Given y\n"
        )
        check = ScenarioNameUniqueCheck()
        draft = ScenarioDraft(
            feature_path=feature_path,
            scenario_name="Same",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "duplicate" in (result.detail or "").lower()


class TestTagsRegisteredCheck:
    def test_no_tags_passes(self, tmp_project_dir: Path):
        check = TagsRegisteredCheck(registered_tags={"@smoke", "@auth"})
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_all_registered_passes(self, tmp_project_dir: Path):
        check = TagsRegisteredCheck(registered_tags={"@smoke", "@auth"})
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@smoke", "@auth"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_unregistered_tag_fails(self, tmp_project_dir: Path):
        check = TagsRegisteredCheck(registered_tags={"@smoke"})
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@unknown_tag"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "@unknown_tag" in (result.detail or "")


class TestStepDefinitionsResolvableCheck:
    def test_all_resolvable_passes(self, tmp_project_dir: Path):
        # Step registry keyed by step keyword + pattern snippet.
        check = StepDefinitionsResolvableCheck(
            registered_patterns=[
                re.compile(r"Given a precondition"),
                re.compile(r"When an action"),
                re.compile(r"Then a result"),
            ]
        )
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nWhen an action\nThen a result",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "When an action", "Then a result"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_unresolvable_step_fails(self, tmp_project_dir: Path):
        check = StepDefinitionsResolvableCheck(
            registered_patterns=[re.compile(r"Given a precondition")]
        )
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given a precondition\nWhen undefined action",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given a precondition", "When undefined action"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "undefined action" in (result.detail or "")


from haileris_v2.verification.mechanical import LifecycleStatusTagPresentCheck


class TestLifecycleStatusTagPresentCheck:
    def test_present_passes(self, tmp_project_dir: Path):
        check = LifecycleStatusTagPresentCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@status-inscribing"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_missing_fails(self, tmp_project_dir: Path):
        check = LifecycleStatusTagPresentCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@smoke"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "lifecycle" in (result.detail or "").lower()

    def test_invalid_status_value_fails(self, tmp_project_dir: Path):
        check = LifecycleStatusTagPresentCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=["@status-bogus"],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"


from haileris_v2.artifacts.mapping import BaseBIDEntry
from haileris_v2.verification.mechanical import SubBidAssignedCheck


class TestSubBidAssignedCheck:
    def test_valid_sub_bid_with_existing_base_passes(self, tmp_project_dir: Path):
        check = SubBidAssignedCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(
            schema_version=1,
            project_id="t",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b",
                    behavior_description="d",
                    scenarios=[],
                    reversion_log=[],
                    post_live_revisions=[],
                    cross_behavior_links=[],
                )
            ],
        )
        result = check.run(draft, mapping)
        assert result.outcome == "pass"

    def test_invalid_base85_char_fails(self, tmp_project_dir: Path):
        check = SubBidAssignedCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid=" ",  # space not in alphabet
            parent_base_bid=Base85BID(value="00000"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"

    def test_parent_base_bid_missing_fails(self, tmp_project_dir: Path):
        check = SubBidAssignedCheck()
        draft = ScenarioDraft(
            feature_path=tmp_project_dir / "test.feature",
            scenario_name="Test",
            gherkin_text="Given x",
            tags=[],
            sub_bid="A",
            parent_base_bid=Base85BID(value="00099"),
            step_texts=["Given x"],
        )
        mapping = MappingArtifact(schema_version=1, project_id="t", base_bids=[])
        result = check.run(draft, mapping)
        assert result.outcome == "fail"
        assert "00099" in (result.detail or "")
