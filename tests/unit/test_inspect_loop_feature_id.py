"""Unit tests for InspectLoop feature_id threading (Plan 12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mage.artifacts.inspect import InspectJournalEntry
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.nodes import PipelineContext


def test_inspect_journal_entry_round_trips_feature_id():
    entry = InspectJournalEntry(
        timestamp=datetime.now(UTC),
        feature_id="feat-1",
        scenario_id="scenario-A",
        iteration=0,
        dimension="mechanical",
        severity="minor",
        route="code",
        finding_id="x",
        location="y",
        issue="z",
        rationale="",
    )
    assert entry.feature_id == "feat-1"
    assert entry.scenario_id == "scenario-A"


def test_inspect_journal_entry_defaults_feature_id_to_empty():
    """Legacy callers without feature_id still construct successfully."""
    entry = InspectJournalEntry(
        timestamp=datetime.now(UTC),
        iteration=0,
        dimension="mechanical",
        severity="minor",
        route="code",
        finding_id="x",
        location="y",
        issue="z",
        rationale="",
    )
    assert entry.feature_id == ""


def test_pipeline_context_feature_id_defaults_to_empty():
    ctx = PipelineContext(
        project_dir=Path("/tmp"),
        mapping=MappingArtifact(schema_version=2, project_id="p"),
        events_log="/tmp/events.jsonl",
    )
    assert ctx.feature_id == ""


def test_pipeline_context_accepts_feature_id():
    ctx = PipelineContext(
        project_dir=Path("/tmp"),
        mapping=MappingArtifact(schema_version=2, project_id="p"),
        events_log="/tmp/events.jsonl",
        feature_id="feat-X",
    )
    assert ctx.feature_id == "feat-X"


def test_inspect_journal_entry_round_trip_yaml():
    """Verify feature_id survives YAML serialization round-trip."""
    import yaml

    entry = InspectJournalEntry(
        timestamp=datetime.now(UTC),
        feature_id="feat-Y",
        scenario_id="scenario-B",
        iteration=1,
        dimension="increment_quality",
        severity="major",
        route="cosmetic",
        finding_id="abc",
        location="src/x.py:1",
        issue="rename var",
        rationale="",
    )
    data = yaml.safe_dump(entry.model_dump(mode="json"))
    restored = InspectJournalEntry.model_validate(yaml.safe_load(data))
    assert restored.feature_id == "feat-Y"
    assert restored.scenario_id == "scenario-B"
