"""Tests for verdict schemas (no I/O yet)."""


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
