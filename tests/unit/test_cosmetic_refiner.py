import asyncio
from pathlib import Path

import pytest

from mage.agents.cosmetic_refiner import CosmeticRefiner
from mage.artifacts.cosmetic import CosmeticPatch


def _raw_queue_entry():
    return {
        "sub_bid": "00000-001",
        "text": "use a constant for the magic number 42",
        "location": {"file": "src/example.py", "line": 15},
        "proposed_by": "IncrementQualityReviewer",
    }


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
async def test_refiner_produces_cosmetic_item_from_raw_dict():
    refiner = CosmeticRefiner()
    canned_payload = {
        "file_path": "src/example.py",
        "line_range": [14, 16],
        "replacement_text": "CONSTANT = 42\n",
        "rationale": "use a constant",
    }
    refiner._agent = _CannedAgent(canned_payload)  # type: ignore[assignment]
    semaphore = asyncio.Semaphore(1)
    result = await refiner.refine(_raw_queue_entry(), semaphore=semaphore)
    assert isinstance(result, CosmeticPatch)
    assert result.sub_bid == "00000-001"
    assert result.file_path == Path("src/example.py")
    assert result.line_range == (14, 16)
    assert "CONSTANT = 42" in result.replacement_text


@pytest.mark.asyncio
async def test_refiner_respects_semaphore_cap():
    """Under cap=2, no more than 2 refines should be active concurrently."""
    refiner = CosmeticRefiner()
    active = 0
    peak = 0

    class CountingAgent:
        async def run(self, prompt: str):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

            class _R:
                output = {  # noqa: RUF012 — test fake; dict is overridden per-instance in __init__
                    "file_path": "src/example.py",
                    "line_range": [1, 1],
                    "replacement_text": "x",
                    "rationale": "x",
                }

            return _R()

    refiner._agent = CountingAgent()  # type: ignore[assignment]
    items = [_raw_queue_entry() for _ in range(6)]
    semaphore = asyncio.Semaphore(2)
    results = await asyncio.gather(
        *[refiner.refine(item, semaphore=semaphore) for item in items]
    )
    assert peak <= 2
    assert len(results) == 6
    assert all(isinstance(r, CosmeticPatch) for r in results)


@pytest.mark.asyncio
async def test_refiner_falls_back_to_stub_on_llm_fail():
    """LLM raises → fallback CosmeticPatch with file_path=None flagged for manual review."""
    refiner = CosmeticRefiner()

    class FailingAgent:
        async def run(self, prompt: str):
            raise RuntimeError("LLM blew up")

    refiner._agent = FailingAgent()  # type: ignore[assignment]
    semaphore = asyncio.Semaphore(1)
    result = await refiner.refine(_raw_queue_entry(), semaphore=semaphore)
    assert result.file_path is None
    assert result.sub_bid == "00000-001"
    assert "use a constant for the magic number 42" in result.rationale
    assert result.line_range == (0, 0)
