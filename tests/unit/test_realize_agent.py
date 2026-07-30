"""Tests for RealizeAgent (carry-forward injection)."""

from __future__ import annotations

from datetime import UTC, datetime


class TestRealizeOutput:
    def test_constructs(self):
        from mage.agents.realize import RealizeOutput

        out = RealizeOutput(files_changed=["src/foo.py"], summary="Implemented foo")
        assert "src/foo.py" in out.files_changed


class TestRealizeAgent:
    def test_prompt_includes_carry_forward(self):
        from mage.agents.realize import RealizeAgent
        from mage.artifacts.inspect import InspectJournalEntry

        agent = RealizeAgent(system_prompt_only=True)
        entry = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="major",
            route="code",
            finding_id="f-1",
            location="src/foo.py:42",
            issue="Missing edge case",
            rationale="Test does not cover empty input",
        )
        prompt = agent.build_prompt(
            step="compute_total",
            scenario_context={"scenario_name": "happy"},
            red_test_path="tests/test_x.py",
            carry_forward=[entry],
            cross_scenario_observations=[],
        )
        assert "Missing edge case" in prompt
        assert "code" in prompt
        assert "src/foo.py:42" in prompt

    def test_prompt_includes_cross_scenario_section(self):
        from mage.agents.realize import RealizeAgent
        from mage.artifacts.inspect import InspectJournalEntry

        agent = RealizeAgent(system_prompt_only=True)
        entry = InspectJournalEntry(
            timestamp=datetime.now(UTC),
            iteration=1,
            dimension="increment_quality",
            severity="minor",
            route="cosmetic",
            finding_id="f-2",
            location="src/bar.py",
            issue="Rephrase",
            rationale="Cosmetic",
        )
        prompt = agent.build_prompt(
            step="compute_total",
            scenario_context={"scenario_name": "happy"},
            red_test_path="tests/test_x.py",
            carry_forward=[],
            cross_scenario_observations=[entry],
        )
        assert (
            "Cross-scenario observations" in prompt
            or "cross-scenario" in prompt.lower()
        )
        assert "Rephrase" in prompt
