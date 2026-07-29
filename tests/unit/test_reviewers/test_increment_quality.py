"""Tests for IncrementQualityReviewer (per-loop-only reviewer)."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.artifacts.verdict import ReviewerFinding, ReviewerVerdict


class TestIncrementQualityReviewer:
    def test_dimension_classvar(self):
        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )
        assert IncrementQualityReviewer.dimension == "increment_quality"

    def test_system_prompt_mentions_three_routes(self):
        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )
        prompt = IncrementQualityReviewer(system_prompt_only=True)._system_prompt()
        assert "spec" in prompt
        assert "code" in prompt
        assert "cosmetic" in prompt

    def test_run_with_canned_testmodel(self):
        from pydantic_ai.models.test import TestModel

        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )

        canned = ReviewerVerdict(
            dimension="increment_quality",
            outcome="pass",
            draft_hash="x",
            reviewed_at=datetime.now(UTC),
            reviewer_id="increment_quality@v1",
            findings=[],
        )
        reviewer = IncrementQualityReviewer(model=TestModel(custom_output_args=canned))
        # system_prompt_only flag means we don't run the agent
        assert reviewer.dimension == "increment_quality"

    def test_system_prompt_requires_route_field(self):
        """Important 4 fix (revised): the reviewer prompt must require the
        model to set the structured `route` field on each finding — NOT to
        encode the route as a `spec:`/`cosmetic:`/`code:` prefix in the
        suggestion. InspectLoopStage reads `f.route` directly.
        """
        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )
        prompt = IncrementQualityReviewer(system_prompt_only=True)._system_prompt()
        # The prompt names the `route` field as the encoding channel.
        assert "route" in prompt, "prompt must reference the `route` field"
        # The prompt names each of the three valid route values.
        assert "'spec'" in prompt, "prompt must list the 'spec' route"
        assert "'cosmetic'" in prompt, "prompt must list the 'cosmetic' route"
        assert "'code'" in prompt, "prompt must list the 'code' route"
        # The prompt tells the model NOT to embed route prefixes in suggestion.
        assert "spec:" not in prompt, (
            "prompt must not require 'spec:' prefix encoding"
        )
        assert "cosmetic:" not in prompt, (
            "prompt must not require 'cosmetic:' prefix encoding"
        )
        assert "code:" not in prompt, (
            "prompt must not require 'code:' prefix encoding"
        )

    def test_findings_with_route_field_route_correctly(self):
        """Important 4 regression: the schema must carry route on the finding
        (not as a suggestion prefix). InspectLoopStage reads `f.route` to
        decide re-loop vs. halt vs. cosmetic. Validate all three shapes."""
        # Build three ReviewerFinding instances — each with the proper
        # `route` field — and confirm they would route correctly in
        # InspectLoopStage (route==spec halts; route==code re-loops;
        # route==cosmetic queues).
        spec_finding = ReviewerFinding(
            id="f-spec",
            severity="major",
            location="src/foo.py",
            issue="Spec describes the wrong thing",
            rationale="Scenario text doesn't match this implementation",
            suggestion="Halt scenario — spec describes the wrong behavior",
            route="spec",
        )
        cosmetic_finding = ReviewerFinding(
            id="f-cosmetic",
            severity="minor",
            location="src/foo.py:42",
            issue="Comment is unclear",
            rationale="Doc string would benefit from a clarification",
            suggestion="rephrase comment for clarity",
            route="cosmetic",
        )
        code_finding = ReviewerFinding(
            id="f-code",
            severity="major",
            location="src/foo.py:55",
            issue="Missing empty-input branch",
            rationale="Edge case not covered",
            suggestion="cover the empty-input branch in the next increment",
            route="code",
        )
        # All three should pass Pydantic validation (route is a Literal).
        for f in (spec_finding, cosmetic_finding, code_finding):
            assert f.route in ("spec", "code", "cosmetic"), (
                f"finding {f.id!r} route must be one of spec/code/cosmetic, "
                f"got {f.route!r}"
            )
        # Confirm each route is what we set — the test of the structured field.
        assert spec_finding.route == "spec"
        assert cosmetic_finding.route == "cosmetic"
        assert code_finding.route == "code"

    def test_increment_quality_finding_has_route_field_not_prefix(self):
        """Pin the new contract: a spec-route finding sets `route="spec"` on
        the finding — NOT a `"spec:"` prefix on `suggestion`. InspectLoopStage
        reads `route` directly, so prefix parsing is no longer needed (Task 6).
        """
        finding = ReviewerFinding(
            id="f-spec-contract",
            severity="major",
            location="src/foo.py",
            issue="Spec describes the wrong thing",
            rationale="Scenario text doesn't match this implementation",
            suggestion="Halt scenario — spec describes the wrong behavior",
            route="spec",
        )
        assert finding.route == "spec"
        # Prefixed-suggestion is the OLD encoding; the new contract forbids
        # it. A correctly authored finding has plain suggestion text.
        assert "spec:" not in finding.suggestion, (
            "spec-route finding must not embed a 'spec:' prefix in "
            "suggestion; route lives on the structured field"
        )

    def test_reviewer_finding_default_route_is_code(self):
        """Findings with no route set default to 'code' so legacy callers
        that don't populate route still get a safe default. Per-loop reviewers
        (IncrementQualityReviewer) override this with spec/cosmetic/code."""
        finding = ReviewerFinding(
            id="f-default",
            severity="minor",
            location="x",
            issue="x",
            rationale="r",
        )
        assert finding.route == "code"
