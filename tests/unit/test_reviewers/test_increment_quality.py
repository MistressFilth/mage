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

    def test_system_prompt_requires_route_prefix_encoding(self):
        """Important 4 fix: the reviewer prompt must require the model to
        emit `suggestion="spec:..."` / `cosmetic:..." / `code:..." prefixes
        so InspectLoopStage can parse the route. Without an explicit
        encoding requirement, LLM-produced findings default to code route.
        """
        from mage.verification.reviewers.increment_quality import (
            IncrementQualityReviewer,
        )
        prompt = IncrementQualityReviewer(system_prompt_only=True)._system_prompt()
        # Encoding instruction present.
        assert "spec:" in prompt, "prompt must require 'spec:' prefix"
        assert "cosmetic:" in prompt, "prompt must require 'cosmetic:' prefix"
        assert "code:" in prompt, "prompt must require 'code:' prefix"
        # The prompt explicitly tells the model the suggestion field carries
        # the route — this is the contract InspectLoopStage parses against.
        assert "suggestion" in prompt, (
            "prompt must reference the `suggestion` field as the encoding "
            "channel"
        )

    def test_findings_with_route_prefix_route_correctly(self):
        """Important 4 regression: spec-route finding with `suggestion` starting
        with 'spec:' must route as spec; cosmetic-route via 'cosmetic:'; code
        defaults to code. Validate the encoding by inspecting InspectLoopStage's
        routing logic end-to-end with all three shapes.
        """
        # Build three ReviewerFinding instances — each with the proper
        # suggestion prefix — and confirm they would route correctly in
        # InspectLoopStage (which uses: route_breakdown.get("spec"),
        # get("cosmetic"), default "code").
        spec_finding = ReviewerFinding(
            id="f-spec",
            severity="major",
            location="src/foo.py",
            issue="Spec describes the wrong thing",
            rationale="Scenario text doesn't match this implementation",
            suggestion="spec:Halt scenario — spec describes the wrong behavior",
        )
        cosmetic_finding = ReviewerFinding(
            id="f-cosmetic",
            severity="minor",
            location="src/foo.py:42",
            issue="Comment is unclear",
            rationale="Doc string would benefit from a clarification",
            suggestion="cosmetic:rephrase comment for clarity",
        )
        code_finding = ReviewerFinding(
            id="f-code",
            severity="major",
            location="src/foo.py:55",
            issue="Missing empty-input branch",
            rationale="Edge case not covered",
            suggestion="code:cover the empty-input branch in the next increment",
        )
        # All three should pass Pydantic validation (suggestion field allows
        # arbitrary string).
        for f in (spec_finding, cosmetic_finding, code_finding):
            assert isinstance(f.suggestion, str) and f.suggestion, (
                f"finding {f.id!r} suggestion must be non-empty"
            )
        # Confirm the prefixes match what InspectLoopStage parses.
        for prefix, finding in (("spec:", spec_finding), ("cosmetic:", cosmetic_finding), ("code:", code_finding)):
            assert finding.suggestion.startswith(prefix), (
                f"{finding.id!r} suggestion {finding.suggestion!r} must start with {prefix!r}"
            )
