"""Inscribe agent: Pydantic-AI agent that drafts scenarios from behavior specs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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

    scenarios: list[ScenarioSpec]
