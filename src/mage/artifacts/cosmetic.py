"""Cosmetic item schema for the per-item cosmetic apply pipeline."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CosmeticPatch(BaseModel):
    """A single concrete cosmetic change proposed by a reviewer (or human).

    `file_path` is project-relative. `line_range` is inclusive on both ends.
    `content_hash` is sha256(replacement_text); used for idempotency when
    `mage cosmetic apply` is re-run.
    `file_path=None` is reserved for fallback stubs that need manual review
    (e.g. LLM refinement failure — see CosmeticRefiner).
    """

    model_config = ConfigDict(frozen=True)

    sub_bid: str
    file_path: Path | None
    line_range: tuple[int, int]
    replacement_text: str
    rationale: str
    proposed_by: str
    applied_at: datetime | None = None
    content_hash: str = Field(default="", validate_default=True)

    @model_validator(mode="after")
    def _validate_line_range_order(self) -> CosmeticPatch:
        if self.line_range[0] > self.line_range[1]:
            raise ValueError(
                f"line_range start ({self.line_range[0]}) must be <= "
                f"end ({self.line_range[1]})"
            )
        return self

    @field_validator("content_hash", mode="before")
    @classmethod
    def _compute_hash(cls, v: str | None, info) -> str:  # type: ignore[no-untyped-def]
        if v:
            return v
        # Pydantic v2: info.data contains previously-validated fields.
        replacement_text = info.data.get("replacement_text", "")
        return hashlib.sha256(replacement_text.encode("utf-8")).hexdigest()
