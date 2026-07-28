"""Tests for EtchStage and EtchAgent."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


class TestEtchAgent:
    def test_red_test_spec_has_step_and_test_path(self):
        from mage.agents.etch import RedTestSpec
        spec = RedTestSpec(
            step_name="compute_total",
            test_path="tests/test_invoice.py",
            test_code="def test_compute_total_empty(): assert compute_total([]) == 0",
        )
        assert spec.step_name == "compute_total"
        assert "test_compute_total_empty" in spec.test_code


class TestEtchStage:
    def test_etch_emits_events_per_step(self, tmp_path):
        from mage.orchestration.events import EventsLog
        from mage.orchestration.etch import EtchStage
        from mage.orchestration.nodes import PipelineContext
        from mage.artifacts.mapping import MappingArtifact

        log = EventsLog(tmp_path / "events.jsonl")
        ctx = PipelineContext(
            project_dir=tmp_path,
            mapping=MappingArtifact(project_id="p1"),
            events_log=log,
            plan_path=tmp_path / "plan.md",
            iteration=0,
        )

        # Stub agent that returns 2 red tests
        class StubAgent:
            def __init__(self, specs):
                self.specs = specs
            def run(self, *, step, scenario_context):
                return self.specs.pop(0)

        from mage.agents.etch import RedTestSpec
        specs = [
            RedTestSpec(step_name="s1", test_path="t1.py", test_code="def test_x(): assert False"),
            RedTestSpec(step_name="s2", test_path="t2.py", test_code="def test_y(): assert False"),
        ]

        stage = EtchStage(log, agent=StubAgent(specs))
        stage._run(ctx)

        events = log.read_all()
        types = [e.event_type.value for e in events]
        assert types.count("etch_started") == 1
        assert types.count("etch_red_confirmed") == 2  # one per step
        assert types.count("etch_completed") == 1
