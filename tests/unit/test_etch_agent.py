"""Tests for the PydanticEtchAgent concrete implementation."""

from __future__ import annotations

import pytest

from mage.agents.etch import EtchAgent, PydanticEtchAgent, RedTestSpec


class _CannedAgent:
    """Async stub returning a fixed dict payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0

    async def run(self, prompt: str):
        self.calls += 1

        class _R:
            def __init__(self, d):
                self.output = d

        return _R(self._payload)


@pytest.mark.asyncio
async def test_pydantic_etch_agent_returns_red_test_spec_from_canned_output():
    agent = PydanticEtchAgent()
    canned = {
        "step_name": "when user clicks save",
        "test_path": "tests/test_save.py",
        "test_code": "def test_save():\n    assert False\n",
    }
    agent._agent = _CannedAgent(canned)  # type: ignore[assignment]
    result = await agent.run(
        step="when user clicks save",
        scenario_context={"scenario_name": "save scenario"},
    )
    assert isinstance(result, RedTestSpec)
    assert result.step_name == "when user clicks save"
    assert result.test_path == "tests/test_save.py"
    assert "assert False" in result.test_code


@pytest.mark.asyncio
async def test_pydantic_etch_agent_prompt_contains_step_and_context():
    agent = PydanticEtchAgent()

    captured_prompts: list[str] = []

    class CapturingAgent:
        async def run(self, prompt: str):
            captured_prompts.append(prompt)

            class _R:
                output = {
                    "test_path": "tests/x.py",
                    "test_code": "def test_x(): assert False\n",
                }

            return _R()

    agent._agent = CapturingAgent()  # type: ignore[assignment]
    await agent.run(
        step="save a file",
        scenario_context={"scenario_name": "save scenario", "tags": ["@save"]},
    )
    assert len(captured_prompts) == 1
    assert "save a file" in captured_prompts[0]
    assert "save scenario" in captured_prompts[0]


@pytest.mark.asyncio
async def test_base_etch_agent_run_raises_not_implemented():
    """The base EtchAgent.run stays abstract — concrete impl is PydanticEtchAgent."""
    base = EtchAgent()
    with pytest.raises(NotImplementedError):
        await base.run(step="x", scenario_context={})
