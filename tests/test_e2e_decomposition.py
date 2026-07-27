"""End-to-end test: full Decomposition flow from Ascertain to finalized Plan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mage.agents.decomposition import ArchitectureSpec, DecompositionAgent, DecompositionOutput
from mage.artifacts.enumeration import BehaviorSpec
from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.decomposition import DecompositionStage
from mage.orchestration.events import EventType, EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig


ASCERTAIN_FULL = """---
feature_id: feat-001
feature_name: User authentication
scope_statement: Email/password login.
in_scope: [login]
out_of_scope: [oauth]
success_criteria: [user can log in]
resolved_ambiguities: []
deferred_questions: []
constraints: []
three_amigos:
  product: ""
  tester: ""
  developer: ""
---

# Ascertain session
"""


def test_full_decomposition_flow_with_mock_agent(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=["api"], components=["auth-svc"], layers=["http"]),
        behaviors=[
            BehaviorSpec(name="auth", description="User logs in"),
            BehaviorSpec(name="logout", description="User logs out", depends_on=["auth"]),
        ],
    )

    host_config = HostConfig(require_plan_approval=False, plan_template_path=None)
    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    result_ctx = stage.run(ctx)

    # All files written
    assert (project_dir / "decomposition.yaml").exists()
    assert (project_dir / "behaviors.yaml").exists()
    assert (project_dir / "plan.md").exists()
    assert (project_dir / "mapping.yaml").exists()

    # Mapping updated
    assert len(result_ctx.mapping.base_bids) == 2
    bnames = {e.behavior_name for e in result_ctx.mapping.base_bids}
    assert bnames == {"auth", "logout"}

    # Plan is finalized (digest matches on load)
    from mage.artifacts.plan import PlanArtifact
    content = PlanArtifact.load(project_dir / "plan.md", log)
    assert "auth" in content
    assert "logout" in content

    # Events emitted
    events = log.read_all()
    event_types = {e.event_type for e in events}
    assert EventType.DECOMPOSITION_STARTED in event_types
    assert EventType.DECOMPOSITION_COMPLETED in event_types
    assert EventType.BEHAVIORS_ENUMERATED in event_types
    assert EventType.PLAN_FINALIZED in event_types


def test_halt_and_resume_cycle(tmp_path):
    """Verify: Decomposition halts -> mage plan revise -> mage run resumes."""
    from mage.artifacts.plan import PlanArtifact, PlanRevisionRequired
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.nodes import PipelineContext, StageNode
    import sys
    from unittest.mock import patch
    from mage.cli import main

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock(spec=DecompositionAgent)
    agent.run.return_value = DecompositionOutput(
        architecture=ArchitectureSpec(parts=["api"], components=[], layers=[]),
        behaviors=[BehaviorSpec(name="auth", description="User logs in")],
    )
    host_config = HostConfig(require_plan_approval=False)
    decomp_stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)

    class HaltAfterDecomp(StageNode):
        name = "halt_after_decomp"
        def _run(self, context):
            raise PlanRevisionRequired(
                reason="Plan ordering is wrong",
                originating_stage="halt_after_decomp",
                affected_behaviors=["00000"],
            )

    graph = PipelineGraph(
        stages=[decomp_stage, HaltAfterDecomp(log)],
        events_log=log,
    )
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)

    with pytest.raises(SystemExit) as exc_info:
        graph.run(ctx)
    assert exc_info.value.code == 0

    # Halt record persisted
    halt_events = [e for e in log.read_all() if e.event_type == EventType.HALT_PERSISTED]
    assert len(halt_events) == 1

    # State persisted
    state_dir = project_dir / ".haileris" / "state"
    assert any(state_dir.iterdir()) if state_dir.exists() else False

    # External edit of plan.md
    plan_path = project_dir / "plan.md"
    plan_path.write_text("# revised plan content\n", encoding="utf-8")

    # Run mage plan revise
    test_argv = [
        "mage", "plan", "revise",
        "--reason", "Reordered behaviors per human review",
        "--approver", "alice",
        "--project-dir", str(project_dir),
    ]
    with patch.object(sys, "argv", test_argv):
        main()

    # Plan load now succeeds with new digest
    content = PlanArtifact.load(plan_path, log)
    assert content == "# revised plan content\n"
