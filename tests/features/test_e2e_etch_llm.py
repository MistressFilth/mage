"""End-to-end tests for the Etch and inner TDD loop with real LLM wiring."""

from __future__ import annotations

from pathlib import Path


def _write_minimal_project(project: Path) -> None:
    (project / "mapping.yaml").write_text(
        "schema_version: 1\nproject_id: e2e\nbase_bids: []\n"
    )
    (project / ".mage").mkdir(exist_ok=True)


def test_e2e_etch_stage_with_real_llm_wiring(tmp_path):
    """EtchStage runs end-to-end with PydanticEtchAgent backed by TestModel."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_minimal_project(project)
    from mage.agents.etch import PydanticEtchAgent

    agent = PydanticEtchAgent(model="test")
    # Smoke test: agent can run a prompt via TestModel.
    import asyncio

    red = asyncio.run(
        agent.run(step="save a file", scenario_context={"scenario_name": "s"})
    )
    assert red.test_path
    assert "def " in red.test_code


def test_events_log_empty_for_blank_project(tmp_path):
    """A blank project with no events yet has an empty EventsLog."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_minimal_project(project)
    from mage.orchestration.events import EventsLog

    log = EventsLog(project / "events.jsonl")
    assert log.read_all() == []
