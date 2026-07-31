"""Unit tests for InspectFeatureStage._append_cosmetics feature_id threading (Plan 13)."""

from __future__ import annotations

from pathlib import Path

from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerFinding
from mage.orchestration.events import EventsLog
from mage.orchestration.inspect_feature import InspectFeatureStage
from mage.orchestration.nodes import PipelineContext


def _make_pipeline_context(tmp_path: Path, feature_id: str) -> PipelineContext:
    mapping = MappingArtifact(schema_version=2, project_id="p", base_bids=[])
    return PipelineContext(
        project_dir=tmp_path,
        mapping=mapping,
        events_log=str(tmp_path / "events.jsonl"),
        feature_id=feature_id,
    )


def test_append_cosmetics_threads_feature_id_from_caller(tmp_path):
    """Cosmetic-queue entry carries the feature_id threaded by the caller, not 'unknown'."""
    context = _make_pipeline_context(tmp_path, feature_id="")  # staging
    stage = InspectFeatureStage.__new__(InspectFeatureStage)  # bypass __init__
    stage.events_log = EventsLog(tmp_path / "events.jsonl")

    finding = ReviewerFinding(
        id="f-1",
        location="src/example.py:1",
        issue="use constant",
        suggestion="use constant",
        rationale="stub rationale",
        severity="minor",
        route="cosmetic",
        citations=[],
    )

    stage._append_cosmetics(
        context,
        [(finding, "testability", None)],
        [{"sub_bid": "00000-001", "name": "scenario-A"}],
        feature_id="feat-X",
    )

    queue = context.mapping.feature_cosmetic_queue
    assert len(queue) == 1
    assert queue[0].get("feature_id") == "feat-X"
    assert queue[0].get("feature_id") != "unknown"


def test_append_cosmetics_propagates_empty_feature_id(tmp_path):
    """Empty feature_id from caller remains empty string in queue (no 'unknown' fallback)."""
    context = _make_pipeline_context(tmp_path, feature_id="")
    stage = InspectFeatureStage.__new__(InspectFeatureStage)
    stage.events_log = EventsLog(tmp_path / "events.jsonl")

    finding = ReviewerFinding(
        id="f-1",
        location="src/example.py:1",
        issue="x",
        suggestion="y",
        rationale="stub rationale",
        severity="minor",
        route="cosmetic",
        citations=[],
    )

    stage._append_cosmetics(
        context,
        [(finding, "testability", None)],
        [{"sub_bid": "00000-001", "name": "scenario-A"}],
        feature_id="",
    )

    queue = context.mapping.feature_cosmetic_queue
    assert len(queue) == 1
    assert queue[0].get("feature_id") == ""
    assert queue[0].get("feature_id") != "unknown"
