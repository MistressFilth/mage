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


def test_base_bid_entry_has_depends_on_and_notes():
    entry = BaseBIDEntry(
        base_bid="00000",
        behavior_name="Authenticate user",
        behavior_description="User logs in with email and password",
        depends_on=[],
        notes="Foundation behavior; everything else depends on this.",
    )
    assert entry.depends_on == []
    assert entry.notes == "Foundation behavior; everything else depends on this."


def test_base_bid_entry_round_trip_with_new_fields(tmp_path):
    entry = BaseBIDEntry(
        base_bid="00001",
        behavior_name="Place order",
        behavior_description="User places an order",
        depends_on=["00000"],
        notes="Depends on authentication.",
    )
    mapping = MappingArtifact(project_id="test-project", base_bids=[entry])
    path = tmp_path / "mapping.yaml"
    mapping.save(path)
    loaded = MappingArtifact.load(path)
    assert loaded.base_bids[0].depends_on == ["00000"]
    assert loaded.base_bids[0].notes == "Depends on authentication."


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


def test_append_scenario_adds_to_matching_base_bid():
    from mage.artifacts.mapping import (
        BaseBIDEntry, MappingArtifact, ScenarioEntry, LifecycleStatus,
    )
    entry = BaseBIDEntry(
        base_bid="00000",
        behavior_name="Authenticate user",
        behavior_description="User logs in",
    )
    mapping = MappingArtifact(project_id="p", base_bids=[entry])

    new_scenario = ScenarioEntry(
        sub_bid="000000",
        scenario_text_hash="abc123",
        lifecycle_status=LifecycleStatus.APPROVED,
    )
    updated = mapping.append_scenario("00000", new_scenario)

    target = next(e for e in updated.base_bids if e.base_bid == "00000")
    assert len(target.scenarios) == 1
    assert target.scenarios[0].sub_bid == "000000"
    # Original mapping is unchanged (frozen).
    assert mapping.base_bids[0].scenarios == []


def test_append_scenario_raises_on_unknown_base_bid():
    from mage.artifacts.mapping import (
        BaseBIDEntry, MappingArtifact, ScenarioEntry, LifecycleStatus, BaseBIDNotFoundError,
    )
    mapping = MappingArtifact(project_id="p", base_bids=[
        BaseBIDEntry(base_bid="00000", behavior_name="x", behavior_description="y"),
    ])
    scenario = ScenarioEntry(
        sub_bid="000000", scenario_text_hash="h", lifecycle_status=LifecycleStatus.APPROVED,
    )
    import pytest
    with pytest.raises(BaseBIDNotFoundError, match="99999"):
        mapping.append_scenario("99999", scenario)


class TestPlan4MappingFields:
    def test_inspect_journal_defaults_empty(self):
        from mage.artifacts.mapping import MappingArtifact
        m = MappingArtifact(project_id="p1")
        assert m.inspect_journal == {}

    def test_feature_inspect_defaults_none(self):
        from mage.artifacts.mapping import MappingArtifact
        m = MappingArtifact(project_id="p1")
        assert m.feature_inspect is None

    def test_feature_cosmetic_queue_defaults_empty(self):
        from mage.artifacts.mapping import MappingArtifact
        m = MappingArtifact(project_id="p1")
        assert m.feature_cosmetic_queue == []

    def test_feature_status_defaults_pending(self):
        from mage.artifacts.mapping import MappingArtifact
        m = MappingArtifact(project_id="p1")
        assert m.feature_status == "pending"

    def test_feature_status_live_assembling(self):
        from mage.artifacts.mapping import MappingArtifact
        m = MappingArtifact(project_id="p1", feature_status="live_assembling")
        assert m.feature_status == "live_assembling"
