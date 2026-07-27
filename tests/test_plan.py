"""Tests for PlanArtifact (digest-pinned Plan with finalize/load/revise)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mage.orchestration.events import EventType, EventsLog


def test_finalize_writes_file_atomically(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    content = "# Plan\n\nBehaviors: 00000, 00001\n"

    digest = PlanArtifact.finalize(plan_path, content, log)

    assert plan_path.exists()
    assert plan_path.read_text() == content
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert digest == expected


def test_finalize_emits_plan_finalized_event(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    digest = PlanArtifact.finalize(plan_path, "# content\n", log)

    events = log.read_all()
    finalized = [e for e in events if e.event_type == EventType.PLAN_FINALIZED]
    assert len(finalized) == 1
    assert finalized[0].payload["plan_path"] == str(plan_path)
    assert finalized[0].payload["plan_sha256"] == digest


def test_finalize_idempotent_with_matching_digest(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    content = "# Plan\n"

    PlanArtifact.finalize(plan_path, content, log)
    # Re-finalize with same content should not raise
    PlanArtifact.finalize(plan_path, content, log)

    events = log.read_all()
    finalized = [e for e in events if e.event_type == EventType.PLAN_FINALIZED]
    assert len(finalized) == 2


def test_finalize_raises_on_digest_mismatch_with_existing_event(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanAlreadyFinalizedError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# original\n", log)
    # Try to finalize with different content
    with pytest.raises(PlanAlreadyFinalizedError):
        PlanArtifact.finalize(plan_path, "# different\n", log)


def test_load_returns_content_when_digest_matches(tmp_path):
    from mage.artifacts.plan import PlanArtifact
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    content = "# Plan\n\nAuth, orders.\n"

    PlanArtifact.finalize(plan_path, content, log)
    loaded = PlanArtifact.load(plan_path, log)

    assert loaded == content


def test_load_raises_when_no_event_exists(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanNotFinalizedError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Orphan\n", encoding="utf-8")

    with pytest.raises(PlanNotFinalizedError):
        PlanArtifact.load(plan_path, log)


def test_load_raises_on_digest_mismatch_after_external_edit(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanDigestMismatchError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# original\n", log)
    # External edit (bypasses revise())
    plan_path.write_text("# tampered\n", encoding="utf-8")

    with pytest.raises(PlanDigestMismatchError):
        PlanArtifact.load(plan_path, log)


def test_load_emits_digest_mismatch_event_before_raising(tmp_path):
    from mage.artifacts.plan import PlanArtifact, PlanDigestMismatchError
    log = EventsLog(tmp_path / "events.jsonl")
    plan_path = tmp_path / "plan.md"

    PlanArtifact.finalize(plan_path, "# original\n", log)
    plan_path.write_text("# tampered\n", encoding="utf-8")

    with pytest.raises(PlanDigestMismatchError):
        PlanArtifact.load(plan_path, log)

    mismatch_events = [
        e for e in log.read_all() if e.event_type == EventType.PLAN_DIGEST_MISMATCH
    ]
    assert len(mismatch_events) == 1
    assert mismatch_events[0].payload["plan_path"] == str(plan_path)
