"""Decomposition agent: Pydantic-AI agent that emits architecture + behavior specs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent

from mage.artifacts.ascertain import AscertainOutput
from mage.artifacts.enumeration import BehaviorSpec
from mage.artifacts.mapping import MappingArtifact


class ArchitectureSpec(BaseModel):
    """Architectural breakdown produced by the Decomposition agent."""

    model_config = ConfigDict(frozen=True)
    parts: list[str]
    components: list[str]
    layers: list[str]
    notes: str = ""


class DecompositionOutput(BaseModel):
    """Combined output of the Decomposition agent."""

    model_config = ConfigDict(frozen=True)
    architecture: ArchitectureSpec
    behaviors: list[BehaviorSpec]


DECOMPOSITION_PROMPT = """You are the Decomposition agent for HAILERIS v2.

Given an Ascertain session's resolved scope, ambiguities, and Three Amigos perspectives,
produce:

1. An `ArchitectureSpec` — the architectural breakdown (parts, components, layers).
2. A list of `BehaviorSpec` — the behaviors the system must exhibit.

Each `BehaviorSpec` has:
- `name`: short behavior name
- `description`: what the behavior does
- `depends_on`: list of OTHER BEHAVIOR NAMES (not BIDs) that must be built first
- `notes`: free-form context for the Inscribe author
- `cross_behavior_links`: list of OTHER BEHAVIOR NAMES that this behavior's scenarios will touch

DO NOT assign or reference BIDs. The system layer assigns BIDs after you finish.

Ascertain session:

{ascertain}

Existing behaviors in the project (read-only context; do not duplicate these names):
{existing_behaviors}
"""


class DecompositionAgent:
    """Pydantic-AI agent that decomposes a feature into architecture + behaviors."""

    def __init__(self, model) -> None:
        self._agent: Agent[None, DecompositionOutput] = Agent(
            model,
            output_type=DecompositionOutput,
            system_prompt="Decomposition agent: produce architecture + behavior specs from Ascertain output.",
        )

    async def run(
        self,
        *,
        ascertain: AscertainOutput,
        existing_mapping: MappingArtifact | None,
    ) -> DecompositionOutput:
        existing_names = (
            [e.behavior_name for e in existing_mapping.base_bids]
            if existing_mapping is not None
            else []
        )
        prompt = DECOMPOSITION_PROMPT.format(
            ascertain=ascertain.model_dump_json(indent=2),
            existing_behaviors=", ".join(existing_names)
            if existing_names
            else "(none)",
        )
        return (await self._agent.run(prompt)).output
