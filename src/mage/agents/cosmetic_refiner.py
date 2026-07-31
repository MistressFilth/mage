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

    Test mode (model is None or the string ``"test"``): bypasses the LLM
    entirely. The refiner synthesizes a CosmeticItem directly from the raw
    queue entry's ``location`` field (``file_path``, ``line_range``) and
    ``text`` (``replacement_text``, ``rationale``). This makes the CLI
    deterministic in ``--model test`` E2E flows without needing per-call
    TestModel configuration.
    """

    def __init__(self, *, model: Any = None) -> None:
        self._is_test_mode = model is None or model == "test"
        if self._is_test_mode:
            # Skip Agent construction; refine() builds CosmeticItem directly.
            self._agent: Agent[None, dict[str, Any]] | None = None
        else:
            self._agent = Agent(
                model=model,
                deps_type=type(None),
                output_type=dict,
                system_prompt=_SYSTEM_PROMPT,
            )

    async def refine(
        self, raw: dict, *, semaphore: asyncio.Semaphore
    ) -> Any:  # returns CosmeticItem; Any here to avoid runtime cycle
        """Refine one raw queue entry into a CosmeticItem.

        Acquires the semaphore first (caller controls fan-out cap). In
        test mode builds the CosmeticItem from raw["location"] without
        an LLM call. On real-LLM failure returns a stub item with
        file_path=None.
        """
        from mage.artifacts.cosmetic import CosmeticItem

        async with semaphore:
            # Test-mode passthrough only fires when no agent has been
            # injected (existing unit tests monkey-patch ``self._agent`` to
            # stub the LLM; that injection must still take precedence).
            if self._is_test_mode and self._agent is None:
                location = raw.get("location") or {}
                file_path = location.get("file")
                line = int(location.get("line", 1))
                text = raw.get("text", "")
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=Path(file_path) if file_path else None,
                    line_range=(max(1, line - 1), line + 1),
                    replacement_text=text + "\n",
                    rationale=text,
                    proposed_by=raw.get("proposed_by", "unknown"),
                )
            try:
                prompt = (
                    f"sub_bid={raw.get('sub_bid')!r}\n"
                    f"text={raw.get('text')!r}\n"
                    f"location={raw.get('location')!r}\n"
                    f"proposed_by={raw.get('proposed_by')!r}"
                )
                result = await self._agent.run(prompt)  # type: ignore[union-attr]
                data = result.output
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=Path(data["file_path"]),
                    line_range=tuple(data["line_range"]),
                    replacement_text=data["replacement_text"],
                    rationale=data.get("rationale", raw.get("text", "")),
                    proposed_by=raw.get("proposed_by", "unknown"),
                )
            except Exception as exc:  # noqa: BLE001 — fallback path for any LLM failure
                return CosmeticItem(
                    sub_bid=raw["sub_bid"],
                    file_path=None,  # type: ignore[arg-type]
                    line_range=(0, 0),
                    replacement_text="",
                    rationale=(
                        f"{raw.get('text', '')} [refiner-error: {type(exc).__name__}]"
                    ),
                    proposed_by=raw.get("proposed_by", "unknown"),
                )
