"""Tests for mechanical author verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from haileris_v2.artifacts.bid import Base85BID
from haileris_v2.artifacts.mapping import MappingArtifact
from haileris_v2.verification.mechanical import (
    CheckResult,
    MechanicalCheck,
    MechanicalVerifier,
    ScenarioDraft,
)
from haileris_v2.verification.mechanical import GherkinSyntaxCheck
from haileris_v2.verification.mechanical import ScenarioNameUniqueCheck


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
