"""Unit tests for ScenarioEntry.feature_id field (Plan 14)."""

from __future__ import annotations

from pathlib import Path

from mage.artifacts.mapping import LifecycleStatus, MappingArtifact, ScenarioEntry


def _make_scenario_entry(
    feature_id: str | None = None, supersedes: str | None = None
) -> ScenarioEntry:
    return ScenarioEntry(
        sub_bid="00000-001",
        scenario_text_hash="abc123",
        lifecycle_status=LifecycleStatus.APPROVED,
        supersedes=supersedes,
        feature_id=feature_id,
    )


def test_scenario_entry_round_trips_with_feature_id():
    """feature_id serializes and de-serializes losslessly."""
    entry = _make_scenario_entry(feature_id="feat-X")
    as_dict = entry.model_dump(mode="python")
    assert as_dict["feature_id"] == "feat-X"
    restored = ScenarioEntry(**as_dict)
    assert restored.feature_id == "feat-X"


def test_scenario_entry_defaults_feature_id_to_none():
    """Legacy callers / legacy YAML produce feature_id=None (no raise)."""
    entry = ScenarioEntry(
        sub_bid="00000-001",
        scenario_text_hash="abc123",
        lifecycle_status=LifecycleStatus.APPROVED,
    )
    assert entry.feature_id is None


def test_mapping_artifact_loads_legacy_base_bids_without_feature_id(tmp_path: Path):
    """A YAML that omits `feature_id` on a ScenarioEntry loads with None."""
    yaml_text = (
        "schema_version: 2\n"
        "project_id: legacy\n"
        "base_bids:\n"
        "  - base_bid: '00000'\n"
        "    behavior_name: b\n"
        "    behavior_description: ''\n"
        "    depends_on: []\n"
        "    notes: ''\n"
        "    scenarios:\n"
        "      - sub_bid: '00000-001'\n"
        "        scenario_text_hash: abc\n"
        "        lifecycle_status: approved\n"
        "        supersedes: null\n"
        "        superseded_by: null\n"
        "        tests: []\n"
        "        derivations: []\n"
        "    reversion_log: []\n"
        "    post_live_revisions: []\n"
        "    cross_behavior_links: []\n"
    )
    path = tmp_path / "mapping.yaml"
    path.write_text(yaml_text)
    loaded = MappingArtifact.load(path)
    entry = loaded.base_bids[0].scenarios[0]
    assert entry.feature_id is None
