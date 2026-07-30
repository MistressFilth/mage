"""Tests for the InscribeAgent."""

from __future__ import annotations

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


@pytest.fixture(autouse=True)
def use_test_model():
    """Force Pydantic-AI agents to use TestModel for deterministic tests."""
    models.ALLOW_MODEL_REQUESTS = False
    yield


@pytest.fixture
def canned_output() -> InscribeOutput:
    """Concrete output that TestModel will return when invoked."""
    return InscribeOutput(
        scenarios=[
            ScenarioSpec(
                name="login succeeds",
                gherkin_body="Given a user\nWhen login\nThen success",
            ),
        ]
    )


@pytest.mark.asyncio
async def test_inscribe_agent_run_returns_inscribe_output(canned_output: InscribeOutput):
    agent = InscribeAgent(model=TestModel(custom_output_args=canned_output))
    behavior = BaseBIDEntry(
        base_bid="00000",
        behavior_name="Authenticate user",
        behavior_description="User logs in with email and password",
    )
    mapping = MappingArtifact(project_id="p", base_bids=[behavior])

    output = await agent.run(behavior=behavior, existing_scenarios=[], mapping=mapping)
    assert isinstance(output, InscribeOutput)
    assert isinstance(output.scenarios, list)
    assert output.scenarios[0].name == "login succeeds"
