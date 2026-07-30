"""Tests for verdict schemas (no I/O yet)."""

import pytest


def test_reviewer_finding_minimal():
    from mage.artifacts.verdict import ReviewerFinding
    f = ReviewerFinding(
        id="f-001",
        severity="critical",
        location="line 5",
        issue="Given uses imperative verb",
        rationale="'Type' is an imperative, not declarative phrasing.",
        suggestion="Replace with: Given the user is on the login form",
    )
    assert f.severity == "critical"
    assert f.citations == []  # default


def test_reviewer_verdict_pass_with_no_findings():
    from mage.artifacts.verdict import ReviewerVerdict
    from datetime import datetime, UTC
    v = ReviewerVerdict(
        dimension="spec_compliance",
        outcome="pass",
        draft_hash="abc123",
        reviewed_at=datetime.now(UTC),
        reviewer_id="spec_compliance@v1",
    )
    assert v.dimension == "spec_compliance"
    assert v.outcome == "pass"
    assert v.findings == []


def test_reviewer_verdict_fail_with_findings():
    from mage.artifacts.verdict import ReviewerVerdict, ReviewerFinding
    from datetime import datetime, UTC
    findings = [
        ReviewerFinding(
            id="f-1",
            severity="major",
            location="line 7",
            issue="ambiguous step",
            rationale="'it' has no clear antecedent.",
        ),
    ]
    v = ReviewerVerdict(
        dimension="scenario_clarity",
        outcome="fail",
        draft_hash="def456",
        reviewed_at=datetime.now(UTC),
        reviewer_id="scenario_clarity@v1",
        findings=findings,
    )
    assert v.outcome == "fail"
    assert len(v.findings) == 1
    assert v.findings[0].rationale == "'it' has no clear antecedent."


def test_reviewer_finding_requires_rationale():
    from mage.artifacts.verdict import ReviewerFinding
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewerFinding(
            id="f-1",
            severity="minor",
            location="line 1",
            issue="x",
            rationale="",  # empty
        )


def test_reviewer_verdict_outcome_literal():
    from mage.artifacts.verdict import ReviewerVerdict
    from datetime import datetime, UTC
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewerVerdict(
            dimension="d",
            outcome="maybe",  # invalid literal
            draft_hash="h",
            reviewed_at=datetime.now(UTC),
            reviewer_id="d@v1",
        )


def test_dimension_summary():
    from mage.artifacts.verdict import DimensionSummary
    s = DimensionSummary(
        outcome="pass",
        reviewer_verdict_ref=".haileris/verdicts/abc/spec_compliance.yaml",
        findings_count=0,
    )
    assert s.outcome == "pass"


def test_reviewer_aggregate_all_pass_yields_approved():
    from mage.artifacts.verdict import ReviewerAggregate, DimensionSummary
    from datetime import datetime, UTC
    per_dim = {
        d: DimensionSummary(outcome="pass", reviewer_verdict_ref=f"{d}.yaml", findings_count=0)
        for d in ["spec_compliance", "scenario_clarity", "step_grammar",
                  "testability", "determinism", "naming_idiom", "lifecycle_tags"]
    }
    agg = ReviewerAggregate(
        draft_hash="h",
        aggregated_at=datetime.now(UTC),
        iteration=1,
        per_dimension=per_dim,
        decision="approved",
        reasoning="all 7 dimensions passed",
    )
    assert agg.decision == "approved"
    assert len(agg.per_dimension) == 7


def test_reviewer_aggregate_decision_literal():
    from mage.artifacts.verdict import ReviewerAggregate
    from datetime import datetime, UTC
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewerAggregate(
            draft_hash="h",
            aggregated_at=datetime.now(UTC),
            iteration=1,
            per_dimension={},
            decision="weird",  # invalid literal
        )


@pytest.mark.asyncio
async def test_verdict_artifact_finalize_writes_yaml_and_emits_event(tmp_path):
    from mage.artifacts.verdict import VerdictArtifact, ReviewerVerdict
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    verdict = ReviewerVerdict(
        dimension="spec_compliance",
        outcome="pass",
        draft_hash="abc",
        reviewed_at=datetime.now(UTC),
        reviewer_id="spec_compliance@v1",
    )
    path = tmp_path / ".haileris" / "verdicts" / "abc" / "spec_compliance.yaml"
    digest = await VerdictArtifact.finalize(path, verdict, log)

    assert path.exists()
    assert len(digest) == 64  # sha256 hex
    events = log.read_all()
    assert any(e.event_type.value == "reviewer_verdict_recorded" for e in events)


@pytest.mark.asyncio
async def test_verdict_artifact_load_returns_model_when_digest_matches(tmp_path):
    from mage.artifacts.verdict import VerdictArtifact, ReviewerVerdict
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    verdict = ReviewerVerdict(
        dimension="d",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="d@v1",
    )
    path = tmp_path / "v.yaml"
    await VerdictArtifact.finalize(path, verdict, log)
    loaded = await VerdictArtifact.load(path, log)
    assert isinstance(loaded, ReviewerVerdict)
    assert loaded.dimension == "d"


@pytest.mark.asyncio
async def test_verdict_artifact_load_raises_on_digest_mismatch(tmp_path):
    from mage.artifacts.verdict import VerdictArtifact, ReviewerVerdict, VerdictDigestMismatchError
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    verdict = ReviewerVerdict(
        dimension="d",
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id="d@v1",
    )
    path = tmp_path / "v.yaml"
    await VerdictArtifact.finalize(path, verdict, log)
    # Tamper with the file
    path.write_text("tampered: yes\n")
    import pytest
    with pytest.raises(VerdictDigestMismatchError):
        await VerdictArtifact.load(path, log)


@pytest.mark.asyncio
async def test_verdict_artifact_finalize_aggregate_uses_aggregate_event(tmp_path):
    from mage.artifacts.verdict import (
        VerdictArtifact, ReviewerAggregate, DimensionSummary,
    )
    from mage.orchestration.events import EventsLog
    from datetime import datetime, UTC
    log = EventsLog(tmp_path / "events.jsonl")
    agg = ReviewerAggregate(
        draft_hash="x",
        aggregated_at=datetime.now(UTC),
        iteration=1,
        per_dimension={
            "spec_compliance": DimensionSummary(
                outcome="pass", reviewer_verdict_ref="r.yaml", findings_count=0
            ),
        },
        decision="approved",
    )
    path = tmp_path / "agg.yaml"
    await VerdictArtifact.finalize(path, agg, log)
    events = log.read_all()
    assert any(e.event_type.value == "review_aggregate_recorded" for e in events)
