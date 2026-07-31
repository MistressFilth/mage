"""Tests for the Decomposition stage."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mage.orchestration.events import EventsLog

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


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "ascertain.md").write_text(ASCERTAIN_FULL, encoding="utf-8")
    return d


@pytest.mark.asyncio
async def test_decomposition_stage_runs_end_to_end(project_dir):
    from mage.agents.decomposition import ArchitectureSpec, DecompositionOutput
    from mage.artifacts.enumeration import BehaviorSpec
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.nodes import PipelineContext

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock()
    from unittest.mock import AsyncMock

    agent.run = AsyncMock(
        return_value=DecompositionOutput(
            architecture=ArchitectureSpec(
                parts=["api"], components=["auth-svc"], layers=["http"]
            ),
            behaviors=[
                BehaviorSpec(name="auth", description="User logs in"),
                BehaviorSpec(
                    name="logout", description="User logs out", depends_on=["auth"]
                ),
            ],
        )
    )

    host_config = MagicMock()
    host_config.require_plan_approval = False
    host_config.plan_template_path = None

    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)

    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)
    result_ctx = await stage.run(ctx)

    assert (project_dir / "decomposition.yaml").exists()
    assert (project_dir / "behaviors.yaml").exists()
    assert (project_dir / "plan.md").exists()
    assert (project_dir / "mapping.yaml").exists()
    assert len(result_ctx.mapping.base_bids) == 2


@pytest.mark.asyncio
async def test_decomposition_stage_writes_decomposition_yaml(project_dir):
    from mage.agents.decomposition import ArchitectureSpec, DecompositionOutput
    from mage.artifacts.enumeration import BehaviorSpec
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.decomposition import DecompositionStage
    from mage.orchestration.nodes import PipelineContext

    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact(project_id="feat-001")

    agent = MagicMock()
    from unittest.mock import AsyncMock

    agent.run = AsyncMock(
        return_value=DecompositionOutput(
            architecture=ArchitectureSpec(parts=["api"], components=[], layers=[]),
            behaviors=[BehaviorSpec(name="auth", description="Login")],
        )
    )

    host_config = MagicMock()
    host_config.require_plan_approval = False
    host_config.plan_template_path = None

    stage = DecompositionStage(events_log=log, agent=agent, host_config=host_config)
    ctx = PipelineContext(project_dir=project_dir, mapping=mapping, events_log=log)
    await stage.run(ctx)

    import yaml

    decomp = yaml.safe_load((project_dir / "decomposition.yaml").read_text())
    assert "architecture" in decomp
    assert "behaviors_input" in decomp
