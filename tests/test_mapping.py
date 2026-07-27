"""Tests for the mapping artifact."""

from __future__ import annotations

from pathlib import Path

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import BaseBIDEntry, LifecycleStatus, MappingArtifact, ScenarioEntry


def base(value: str, name: str = "b") -> BaseBIDEntry:
    return BaseBIDEntry(base_bid=value, behavior_name=name, behavior_description="d")


class TestLifecycleStatus:
    def test_values(self):
        assert [s.value for s in LifecycleStatus] == ["inscribing", "approved", "live", "deprecated", "retired"]


class TestScenarioEntry:
    def test_minimal_construction(self):
        entry = ScenarioEntry(sub_bid="A", scenario_text_hash="abc123", lifecycle_status=LifecycleStatus.INSCRIBING)
        assert entry.sub_bid == "A"
        assert entry.lifecycle_status == LifecycleStatus.INSCRIBING


class TestBaseBIDEntry:
    def test_minimal_construction(self):
        assert base("00000").base_bid == "00000"


class TestMappingArtifact:
    def test_empty_artifact(self):
        artifact = MappingArtifact(project_id="test-project")
        assert artifact.project_id == "test-project"
        assert artifact.base_bids == []

    def test_next_base_bid_when_empty(self):
        assert MappingArtifact(project_id="test").next_base_bid().value == "00000"

    def test_next_base_bid_with_existing(self):
        artifact = MappingArtifact(project_id="test", base_bids=[base("00000"), base("00005")])
        assert artifact.next_base_bid().value == "00006"

    def test_lookup_sub_bid(self):
        scenario = ScenarioEntry(sub_bid="A", scenario_text_hash="h1", lifecycle_status=LifecycleStatus.LIVE, tests=["test_login"], derivations=["src/auth.py"])
        artifact = MappingArtifact(project_id="test", base_bids=[base("00000") .model_copy(update={"scenarios": [scenario]})])
        assert artifact.lookup_sub_bid(Base85BID(value="00000"), "A") == scenario
        assert artifact.lookup_sub_bid(Base85BID(value="00000"), "B") is None

    def test_lookup_sub_bid_not_found(self):
        assert MappingArtifact(project_id="test").lookup_sub_bid(Base85BID(value="00000"), "A") is None


class TestMappingArtifactIO:
    def test_round_trip(self, tmp_project_dir: Path):
        original = MappingArtifact(project_id="round-trip", base_bids=[base("00000").model_copy(update={"scenarios": [ScenarioEntry(sub_bid="A", scenario_text_hash="hash1", lifecycle_status=LifecycleStatus.APPROVED)]})])
        path = tmp_project_dir / "mapping.yaml"
        original.save(path)
        loaded = MappingArtifact.load(path)
        assert loaded.project_id == "round-trip"
        assert loaded.base_bids[0].scenarios[0].sub_bid == "A"

    def test_save_is_atomic(self, tmp_project_dir: Path):
        path = tmp_project_dir / "mapping.yaml"
        MappingArtifact(project_id="atomic").save(path)
        assert list(tmp_project_dir.glob("*.tmp")) == []
        assert path.exists()
