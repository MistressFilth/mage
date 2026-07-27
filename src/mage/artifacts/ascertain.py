"""Ascertain output schema: structured record of resolved ambiguities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


class AscertainSchemaError(Exception):
    """Raised when Ascertain output cannot be parsed."""


class ResolvedAmbiguity(BaseModel):
    model_config = ConfigDict(frozen=True)
    question: str
    decision: str
    rationale: str
    resolved_by: str


class ThreeAmigos(BaseModel):
    model_config = ConfigDict(frozen=True)
    product: str = ""
    tester: str = ""
    developer: str = ""


class AscertainOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    feature_id: str
    feature_name: str
    scope_statement: str
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    success_criteria: list[str] = []
    resolved_ambiguities: list[ResolvedAmbiguity] = []
    deferred_questions: list[str] = []
    constraints: list[str] = []
    three_amigos: ThreeAmigos = ThreeAmigos()
    body: str = ""

    @field_validator("feature_id", "feature_name", "scope_statement")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


def parse_ascertain(path: Path) -> AscertainOutput:
    """Parse Ascertain output (Markdown + YAML frontmatter) into AscertainOutput.

    Raises AscertainSchemaError if the file is missing, has no frontmatter,
    or the frontmatter fails validation.
    """
    if not path.exists():
        raise AscertainSchemaError(f"Ascertain file does not exist: {path}")

    text = path.read_text(encoding="utf-8")

    # Split frontmatter from body
    if not text.startswith("---\n"):
        raise AscertainSchemaError(
            f"Ascertain file {path} does not start with YAML frontmatter (---)"
        )

    # Normalize: ensure a trailing newline so the closing "---" is followed by "\n".
    # Files authored without a final newline (e.g. """---""") would otherwise fail
    # the split below.
    if not text.endswith("\n"):
        text = text + "\n"

    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise AscertainSchemaError(
            f"Ascertain file {path} has malformed frontmatter (missing closing ---)"
        )

    frontmatter_text = parts[1]
    body = parts[2]

    try:
        frontmatter: dict[str, Any] = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        raise AscertainSchemaError(f"Ascertain frontmatter is invalid YAML: {e}") from e

    if not isinstance(frontmatter, dict):
        raise AscertainSchemaError(
            f"Ascertain frontmatter must be a YAML mapping, got {type(frontmatter).__name__}"
        )

    try:
        return AscertainOutput(**frontmatter, body=body)
    except Exception as e:
        raise AscertainSchemaError(f"Ascertain frontmatter validation failed: {e}") from e
