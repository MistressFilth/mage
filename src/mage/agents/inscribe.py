"""Inscribe agent: Pydantic-AI agent that drafts scenarios from behavior specs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


class ScenarioSpec(BaseModel):
    """A single scenario drafted by the Inscribe agent.

    Sub-BID and scenario_text_hash are NOT assigned here — they are assigned
    by the InscribeStage at the moment the scenario transitions to APPROVED.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    gherkin_body: str
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    cross_behavior_tags: list[str] = Field(default_factory=list)


class InscribeOutput(BaseModel):
    """Combined output of the Inscribe agent for one behavior."""

    model_config = ConfigDict(frozen=True)

    scenarios: list[ScenarioSpec]  # noqa: RUF012


INSCRIBE_PROMPT = """You are the Inscribe agent for HAILERIS v2.

Given a behavior spec, draft scenarios that fully cover the behavior's description.

Each scenario has:
- name: short, unique within behavior (kebab-case or snake_case)
- gherkin_body: full Given/When/Then block
- tags: list of @-prefixed tags
- notes: free-form context for the Etch author
- cross_behavior_tags: list of @-prefixed cross-behavior tag references

Honor depends_on and cross_behavior_links. Reuse existing scenarios where possible —
only draft new ones if the existing set has gaps.

DO NOT assign or reference BIDs. Sub-BIDs and hashes are assigned by the system
at APPROVED.

Behavior spec:

{behavior}

Existing scenarios under this behavior:

{existing_scenarios}

Sibling behaviors (read-only context):

{sibling_behaviors}
"""


class InscribeAgent:
    """Pydantic-AI agent that drafts scenarios from a behavior spec."""

    def __init__(self, model) -> None:
        self._agent: Agent[None, InscribeOutput] = Agent(
            model,
            output_type=InscribeOutput,
            system_prompt="Inscribe agent: draft scenarios from behavior spec.",
        )

    def run(
        self,
        *,
        behavior: BaseBIDEntry,
        existing_scenarios: list,
        mapping: MappingArtifact,
    ) -> InscribeOutput:
        existing_str = "\n".join(
            f"- {s.name}: {s.gherkin_body[:80]}..." for s in existing_scenarios
        ) or "(none)"
        sibling_names = [
            e.behavior_name for e in mapping.base_bids
            if e.base_bid != behavior.base_bid
        ]
        prompt = INSCRIBE_PROMPT.format(
            behavior=behavior.model_dump_json(indent=2),
            existing_scenarios=existing_str,
            sibling_behaviors=", ".join(sibling_names) if sibling_names else "(none)",
        )
        return self._agent.run_sync(prompt).output
