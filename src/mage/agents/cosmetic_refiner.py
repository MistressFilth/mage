"""CosmeticRefiner: turn raw cosmetic queue entries into concrete CosmeticItems."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

_SYSTEM_PROMPT = """You refine a cosmetic suggestion into a concrete file edit.

Given a raw queue entry with `sub_bid`, `text`, `location` (file + line),
and `proposed_by`, produce a dict with:
- file_path: the file from location.file (string)
- line_range: [line - 1, line + 1] — surrounding context (2-element list)
- replacement_text: the proposed fix as it should appear in the file (string)
- rationale: a short reason (string)
"""


class CosmeticRefiner:
    """LLM-driven refiner for cosmetic queue entries.

    `refine()` is async and takes an `asyncio.Semaphore` to allow the caller
    to cap concurrent LLM fan-out (see HostConfig.max_concurrent_llm_calls).
    On LLM failure, returns a stub CosmeticItem with file_path=None so the
    caller can decide how to surface the failure (see COSMETIC_REFINER_FALLBACK
    event).
    """

    def __init__(self, *, model: Any = None) -> None:
        self._agent: Agent[None, dict[str, Any]] = Agent(
            model=model or "test",
            deps_type=type(None),
            output_type=dict,
            system_prompt=_SYSTEM_PROMPT,
        )

    async def refine(
        self, raw: dict, *, semaphore: asyncio.Semaphore
    ) -> "Any":  # returns CosmeticItem; Any here to avoid runtime cycle
        """Refine one raw queue entry into a CosmeticItem.

        Acquires the semaphore first (caller controls fan-out cap). On LLM
        failure returns a stub item with file_path=None.
        """
        from mage.artifacts.cosmetic import CosmeticItem

        async with semaphore:
            try:
                prompt = (
                    f"sub_bid={raw.get('sub_bid')!r}\n"
                    f"text={raw.get('text')!r}\n"
                    f"location={raw.get('location')!r}\n"
                    f"proposed_by={raw.get('proposed_by')!r}"
                )
                result = await self._agent.run(prompt)
                data = result.output
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=Path(data["file_path"]),
                    line_range=tuple(data["line_range"]),
                    replacement_text=data["replacement_text"],
                    rationale=data.get("rationale", raw.get("text", "")),
                    proposed_by=raw.get("proposed_by", "unknown"),
                )
            except Exception:  # noqa: BLE001 — fallback path for any LLM failure
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=None,  # type: ignore[arg-type]
                    line_range=(0, 0),
                    replacement_text="",
                    rationale=raw.get("text", ""),
                    proposed_by=raw.get("proposed_by", "unknown"),
                )
