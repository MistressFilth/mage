"""Tests for the mapping artifact."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)


def base(value: str, name: str = "b") -> BaseBIDEntry:
    return BaseBIDEntry(base_bid=value, behavior_name=name, behavior_description="d")


class TestLifecycleStatus:
    def test_values(self):
        assert [s.value for s in LifecycleStatus] == [
            "inscribing",
            "approved",
            "live",
            "deprecated",
            "retired",
        ]


class TestScenarioEntry:
    def test_minimal_construction(self):
        entry = ScenarioEntry(
            sub_bid="A",
            scenario_text_hash="abc123",
            lifecycle_status=LifecycleStatus.INSCRIBING,
        )
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


@pytest.mark.asyncio
async def test_base_bid_entry_round_trip_with_new_fields(tmp_path):
    entry = BaseBIDEntry(
        base_bid="00001",
        behavior_name="Place order",
        behavior_description="User places an order",
        depends_on=["00000"],
        notes="Depends on authentication.",
    )
    mapping = MappingArtifact(project_id="test-project", base_bids=[entry])
    path = tmp_path / "mapping.yaml"
    await mapping.save(path)
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
        artifact = MappingArtifact(
            project_id="test", base_bids=[base("00000"), base("00005")]
        )
        assert artifact.next_base_bid().value == "00006"

    def test_lookup_sub_bid(self):
        scenario = ScenarioEntry(
            sub_bid="A",
            scenario_text_hash="h1",
            lifecycle_status=LifecycleStatus.LIVE,
            tests=["test_login"],
            derivations=["src/auth.py"],
        )
        artifact = MappingArtifact(
            project_id="test",
            base_bids=[base("00000").model_copy(update={"scenarios": [scenario]})],
        )
        assert artifact.lookup_sub_bid(Base85BID(value="00000"), "A") == scenario
        assert artifact.lookup_sub_bid(Base85BID(value="00000"), "B") is None

    def test_lookup_sub_bid_not_found(self):
        assert (
            MappingArtifact(project_id="test").lookup_sub_bid(
                Base85BID(value="00000"), "A"
            )
            is None
        )


class TestMappingArtifactIO:
    @pytest.mark.asyncio
    async def test_round_trip(self, tmp_project_dir: Path):
        original = MappingArtifact(
            project_id="round-trip",
            base_bids=[
                base("00000").model_copy(
                    update={
                        "scenarios": [
                            ScenarioEntry(
                                sub_bid="A",
                                scenario_text_hash="hash1",
                                lifecycle_status=LifecycleStatus.APPROVED,
                            )
                        ]
                    }
                )
            ],
        )
        path = tmp_project_dir / "mapping.yaml"
        await original.save(path)
        loaded = MappingArtifact.load(path)
        assert loaded.project_id == "round-trip"
        assert loaded.base_bids[0].scenarios[0].sub_bid == "A"

    @pytest.mark.asyncio
    async def test_save_is_atomic(self, tmp_project_dir: Path):
        path = tmp_project_dir / "mapping.yaml"
        await MappingArtifact(project_id="atomic").save(path)
        assert list(tmp_project_dir.glob("*.tmp")) == []
        assert path.exists()


def test_append_scenario_adds_to_matching_base_bid():
    from mage.artifacts.mapping import (
        BaseBIDEntry,
        LifecycleStatus,
        MappingArtifact,
        ScenarioEntry,
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
        BaseBIDEntry,
        BaseBIDNotFoundError,
        LifecycleStatus,
        MappingArtifact,
        ScenarioEntry,
    )

    mapping = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00000", behavior_name="x", behavior_description="y"),
        ],
    )
    scenario = ScenarioEntry(
        sub_bid="000000",
        scenario_text_hash="h",
        lifecycle_status=LifecycleStatus.APPROVED,
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
        assert m.cosmetic_findings == []

    def test_feature_status_defaults_pending(self):
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1")
        assert m.feature_status == "pending"

    def test_feature_status_live_assembling(self):
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1", feature_status="live_assembling")
        assert m.feature_status == "live_assembling"


class TestPlan4MappingMethods:
    def test_append_inspect_journal(self):
        from mage.artifacts.inspect import InspectJournalEntry
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1")
        entry = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="major",
            route="code",
            finding_id="f-1",
            location="src/foo.py",
            issue="x",
            rationale="y",
        )
        m2 = m.append_inspect_journal("00000-0", entry)
        assert m is not m2  # immutable
        assert len(m2.inspect_journal["00000-0"]) == 1
        assert m2.inspect_journal["00000-0"][0]["finding_id"] == "f-1"

    def test_append_inspect_journal_appends_to_existing(self):
        from mage.artifacts.inspect import InspectJournalEntry
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1")
        entry1 = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="major",
            route="code",
            finding_id="f-1",
            location="src/foo.py",
            issue="x",
            rationale="y",
        )
        entry2 = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=2,
            dimension="increment_quality",
            severity="minor",
            route="cosmetic",
            finding_id="f-2",
            location="src/foo.py",
            issue="x",
            rationale="y",
        )
        m = m.append_inspect_journal("00000-0", entry1)
        m = m.append_inspect_journal("00000-0", entry2)
        assert len(m.inspect_journal["00000-0"]) == 2

    def test_attach_feature_inspect(self):
        from mage.artifacts.inspect import InspectArtifactRef
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1")
        ref = InspectArtifactRef(
            inspect_path=".haileris/inspect/feat-1/1.yaml",
            inspect_sha256="abc",
            finalized_at=datetime.now(UTC),
        )
        m2 = m.attach_feature_inspect(ref)
        assert m2.feature_inspect is not None
        assert m2.feature_inspect["inspect_sha256"] == "abc"

    def test_append_cosmetic(self):
        from mage.artifacts.inspect import CosmeticFinding
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1")
        item = CosmeticFinding(
            sub_bid="00000-0",
            scenario_name="happy",
            location="Given step",
            text="Rephrase",
            proposed_by="increment_quality",
        )
        m2 = m.append_cosmetic_finding("feat-1", item)
        assert len(m2.cosmetic_findings) == 1
        assert m2.cosmetic_findings[0]["text"] == "Rephrase"

    def test_feature_resume_state_halted(self):
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1", feature_status="halted")
        state = m.feature_resume_state()
        assert state["status"] == "halted"
        assert state["should_resume"] is True

    def test_feature_resume_state_running(self):
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1", feature_status="live_assembling")
        state = m.feature_resume_state()
        assert state["should_resume"] is False


class TestMappingArtifactValidation:
    """Important 5 fix: MappingArtifact.model_validator rejects malformed
    inspect_journal / feature_cosmetic_queue / feature_inspect at load time
    (or save time) instead of letting bad data flow through to a later
    consumer that fails cryptically."""

    def test_valid_empty_passes(self):
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(project_id="p1")
        assert m.inspect_journal == {}
        assert m.cosmetic_findings == []
        assert m.feature_inspect is None

    def test_valid_journal_entry_passes(self):
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(
            project_id="p1",
            inspect_journal={"00000-0": [{"dimension": "mechanical", "route": "code"}]},
        )
        assert m.inspect_journal["00000-0"][0]["dimension"] == "mechanical"

    def test_invalid_inspect_journal_key_not_string(self, tmp_path: Path):
        """Validator rejects non-string keys at load time."""
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        with pytest.raises(ValidationError):
            MappingArtifact.model_validate(
                {"project_id": "p1", "inspect_journal": {123: []}}
            )

    def test_invalid_inspect_journal_empty_key(self):
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        with pytest.raises(ValidationError):
            MappingArtifact.model_validate(
                {"project_id": "p1", "inspect_journal": {"": []}}
            )

    def test_invalid_inspect_journal_value_not_list(self):
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        with pytest.raises(ValidationError):
            MappingArtifact.model_validate(
                {"project_id": "p1", "inspect_journal": {"00000-0": "not-a-list"}}
            )

    def test_invalid_inspect_journal_entry_not_dict(self):
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        with pytest.raises(ValidationError):
            MappingArtifact.model_validate(
                {"project_id": "p1", "inspect_journal": {"00000-0": ["not-a-dict"]}}
            )

    def test_invalid_feature_cosmetic_queue_item_not_dict(self):
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        with pytest.raises(ValidationError):
            MappingArtifact.model_validate(
                {"project_id": "p1", "feature_cosmetic_queue": ["not-a-dict"]}
            )

    def test_invalid_feature_inspect_not_dict(self):
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        with pytest.raises(ValidationError):
            MappingArtifact.model_validate(
                {"project_id": "p1", "feature_inspect": "not-a-dict"}
            )

    @pytest.mark.asyncio
    async def test_round_trip_through_yaml_preserves_validation(self, tmp_path: Path):
        """Validation must apply on load() too, not only on model_validate()."""
        from mage.artifacts.mapping import MappingArtifact

        m = MappingArtifact(
            project_id="p1",
            inspect_journal={"00000-0": [{"route": "code", "dimension": "mechanical"}]},
            feature_cosmetic_queue=[{"feature_id": "feat-1", "text": "rephrase"}],
        )
        path = tmp_path / "mapping.yaml"
        await m.save(path)
        loaded = MappingArtifact.load(path)
        assert loaded.inspect_journal == {
            "00000-0": [{"route": "code", "dimension": "mechanical"}]
        }
        assert loaded.cosmetic_findings == [
            {"feature_id": "feat-1", "text": "rephrase"}
        ]

    def test_save_rejects_malformed_journal(self, tmp_path: Path):
        """The save() path also goes through model construction; manual
        construction with bad data must raise loudly.
        """
        import pytest
        from pydantic import ValidationError

        from mage.artifacts.mapping import MappingArtifact

        # ValidationError at construction time, before save is invoked.
        with pytest.raises(ValidationError):
            MappingArtifact(
                project_id="p1",
                inspect_journal={"k": "not-a-list"},
            )


class TestCosmeticFindingsAlias:
    """Plan 18: cosmetic_findings Python attr round-trips via feature_cosmetic_queue on-disk key."""

    def test_load_via_alias_key_populates_cosmetic_findings(self):
        from mage.artifacts.mapping import MappingArtifact

        artifact = MappingArtifact.model_validate(
            {
                "schema_version": 2,
                "project_id": "demo",
                "feature_cosmetic_queue": [
                    {"sub_bid": "00000-001", "feature_id": "feat-1"}
                ],
            }
        )
        assert len(artifact.cosmetic_findings) == 1
        assert artifact.cosmetic_findings[0]["feature_id"] == "feat-1"

    def test_dump_with_alias_serializes_as_feature_cosmetic_queue(self):
        from mage.artifacts.inspect import CosmeticFinding
        from mage.artifacts.mapping import MappingArtifact

        artifact = MappingArtifact(
            project_id="demo",
            cosmetic_findings=[
                CosmeticFinding(
                    sub_bid="00000-001",
                    scenario_name="s",
                    location="src/x.py:1",
                    text="tidy imports",
                    proposed_by="increment_quality",
                ).model_dump(mode="python")
                | {"feature_id": "feat-1"},
                CosmeticFinding(
                    sub_bid="00000-002",
                    scenario_name="s2",
                    location="src/x.py:5",
                    text="swap to walrus",
                    proposed_by="increment_quality",
                ).model_dump(mode="python")
                | {"feature_id": "feat-2"},
            ],
        )
        dumped = artifact.model_dump(mode="json", by_alias=True)
        assert "feature_cosmetic_queue" in dumped
        assert "cosmetic_findings" not in dumped
        assert len(dumped["feature_cosmetic_queue"]) == 2
        dumped_first = dumped["feature_cosmetic_queue"][0]
        assert dumped_first["feature_id"] == "feat-1"
        assert dumped_first["text"] == "tidy imports"
        assert dumped_first["sub_bid"] == "00000-001"
        dumped_second = dumped["feature_cosmetic_queue"][1]
        assert dumped_second["feature_id"] == "feat-2"
        assert dumped_second["text"] == "swap to walrus"

    def test_save_writes_alias_key_and_round_trips(self, tmp_path):
        """Plan 18 reviewer fix #1: save() must serialize under feature_cosmetic_queue.

        Before the fix, ``model_dump(mode="json")`` was called without
        ``by_alias=True`` and emitted ``cosmetic_findings`` as the YAML key,
        breaking the on-disk compatibility promise. This test calls the real
        ``save()`` path, parses the YAML it wrote, and confirms the alias key
        is what appears on disk.
        """
        import asyncio

        from mage.artifacts.inspect import CosmeticFinding
        from mage.artifacts.mapping import MappingArtifact

        artifact = MappingArtifact(
            project_id="demo",
            cosmetic_findings=[
                CosmeticFinding(
                    sub_bid="00000-001",
                    scenario_name="s",
                    location="src/x.py:1",
                    text="tidy imports",
                    proposed_by="increment_quality",
                ).model_dump(mode="python")
                | {"feature_id": "feat-1"},
            ],
        )
        path = tmp_path / "plan18_save_alias_demo.yaml"
        asyncio.run(artifact.save(path))

        raw = path.read_text()
        assert "feature_cosmetic_queue:" in raw
        assert "cosmetic_findings:" not in raw

        loaded = MappingArtifact.load(path)
        assert len(loaded.cosmetic_findings) == 1
        assert loaded.cosmetic_findings[0]["feature_id"] == "feat-1"
        assert loaded.cosmetic_findings[0]["text"] == "tidy imports"
