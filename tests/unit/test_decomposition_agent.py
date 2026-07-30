"""Tests for the Decomposition Pydantic-AI agent (uses TestModel)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai import models

from mage.agents.decomposition import DecompositionAgent
from mage.artifacts.ascertain import AscertainOutput, ThreeAmigos


@pytest.fixture(autouse=True)
def use_test_model():
    """Force all Pydantic-AI agents to use TestModel for deterministic tests."""
    models.ALLOW_MODEL_REQUESTS = False
    yield


def _ascertain() -> AscertainOutput:
    return AscertainOutput(
        feature_id="feat-001",
        feature_name="User authentication",
        scope_statement="Email/password login for v1.",
        three_amigos=ThreeAmigos(
            product="Focus on simplest happy path",
            tester="Verify error states",
            developer="Integrate with existing auth",
        ),
    )


@pytest.mark.asyncio
async def test_decomposition_agent_returns_architecture_and_behaviors():
    agent = DecompositionAgent(model=TestModel())
    output = await agent.run(ascertain=_ascertain(), existing_mapping=None)
    assert output.architecture is not None
    assert isinstance(output.behaviors, list)
    assert len(output.behaviors) >= 1
    # No BIDs in agent output
    for behavior in output.behaviors:
        assert not hasattr(behavior, "id")


@pytest.mark.asyncio
async def test_decomposition_agent_receives_existing_mapping_context():
    from mage.artifacts.mapping import MappingArtifact, BaseBIDEntry
    agent = DecompositionAgent(model=TestModel())
    mapping = MappingArtifact(
        project_id="p",
        base_bids=[BaseBIDEntry(base_bid="00005", behavior_name="existing", behavior_description="existing")],
    )
    output = await agent.run(ascertain=_ascertain(), existing_mapping=mapping)
    assert output is not None
