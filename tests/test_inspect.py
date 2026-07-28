"""Tests for the InspectArtifact schemas (Plan 4 schemas only; finalize/load in Task 4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mage.artifacts.inspect import (
    CosmeticItem,
    InspectArtifactContent,
    InspectArtifactRef,
    InspectJournalEntry,
    ScenarioInspectStatus,
)


class TestInspectJournalEntry:
    def test_constructs_with_required_fields(self):
        entry = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="major",
            route="code",
            finding_id="f-001",
            location="src/foo.py:42",
            issue="Missing edge case",
            rationale="Test does not cover empty input",
        )
        assert entry.dimension == "increment_quality"
        assert entry.route == "code"

    def test_route_is_restricted_to_three_values(self):
        with pytest.raises(ValidationError):
            InspectJournalEntry(
                timestamp=datetime.now(UTC),
                iteration=1,
                dimension="increment_quality",
                severity="major",
                route="garbage",  # invalid
                finding_id="f-001",
                location="src/foo.py",
                issue="x",
                rationale="y",
            )

    def test_frozen(self):
        entry = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="major",
            route="code",
            finding_id="f-001",
            location="src/foo.py",
            issue="x",
            rationale="y",
        )
        with pytest.raises(ValidationError):
            entry.finding_id = "different"  # type: ignore[misc]


class TestScenarioInspectStatus:
    def test_live_status(self):
        s = ScenarioInspectStatus(sub_bid="00000-0", scenario_name="happy", status="live")
        assert s.status == "live"

    def test_needs_refactor_status(self):
        s = ScenarioInspectStatus(sub_bid="00000-0", scenario_name="x", status="needs_refactor")
        assert s.status == "needs_refactor"

    def test_approved_with_caveat_status(self):
        s = ScenarioInspectStatus(sub_bid="00000-0", scenario_name="x", status="approved_with_caveat")
        assert s.status == "approved_with_caveat"


class TestCosmeticItem:
    def test_constructs(self):
        item = CosmeticItem(
            sub_bid="00000-0",
            scenario_name="happy",
            location="Given step: line 3",
            text="Rephrase for clarity",
            proposed_by="increment_quality",
        )
        assert item.sub_bid == "00000-0"


class TestInspectArtifactRef:
    def test_constructs_with_digest(self):
        ref = InspectArtifactRef(
            inspect_path=".haileris/inspect/feat-1/1.yaml",
            inspect_sha256="abc123",
            finalized_at=datetime.now(UTC),
        )
        assert ref.inspect_sha256 == "abc123"


class TestInspectArtifactContent:
    def test_constructs_minimal(self):
        from mage.artifacts.verdict import ReviewerVerdict
        content = InspectArtifactContent(
            feature_id="feat-1",
            inspected_at=datetime.now(UTC),
            iteration=1,
            eof_max_iterations=3,
            scenarios=[],
            per_reviewer=[],
            critical=[],
            important=[],
            minor=[],
            cross_scenario=[],
            ready_to_merge=False,
            ledger_markdown="",
        )
        assert content.feature_id == "feat-1"
        assert content.eof_max_iterations == 3

    def test_no_digest_field_in_content(self):
        """Per spec R24 / GC-7: digest is event payload, not a content field."""
        from mage.artifacts.inspect import InspectArtifactContent
        fields = InspectArtifactContent.model_fields.keys()
        assert "digest" not in fields
        assert "inspect_sha256" not in fields
        assert "digest_placeholder" not in fields
