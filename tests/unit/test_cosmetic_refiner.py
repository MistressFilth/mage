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
    refiner._agent = _CannedAgent(canned_payload)  # type: ignore[assignment, ty:invalid-assignment]
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
                def __init__(self) -> None:
                    self.output = {
                        "file_path": "src/example.py",
                        "line_range": [1, 1],
                        "replacement_text": "x",
                        "rationale": "x",
                    }

            return _R()

    refiner._agent = CountingAgent()  # type: ignore[assignment, ty:invalid-assignment]
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

    refiner._agent = FailingAgent()  # type: ignore[assignment, ty:invalid-assignment]
    semaphore = asyncio.Semaphore(1)
    result = await refiner.refine(_raw_queue_entry(), semaphore=semaphore)
    assert result.file_path is None
    assert result.sub_bid == "00000-001"
    assert "use a constant for the magic number 42" in result.rationale
    assert result.line_range == (0, 0)


@pytest.mark.asyncio
async def test_refiner_accepts_string_shaped_location():
    """A bare-string `location` must not crash `refine` (Important #2).

    The spec documents location as `{"file": ..., "line": ...}`, but
    raw queues may carry a bare string path. The refiner normalizes
    both shapes to a dict internally so the rest of the function is
    uniform.
    """
    refiner = CosmeticRefiner(model="test")  # test mode → no LLM call
    semaphore = asyncio.Semaphore(1)
    raw = {
        "sub_bid": "00000-002",
        "text": "trim trailing whitespace",
        "location": "src/strloc.py",  # bare string, NOT a dict
        "proposed_by": "IncrementQualityReviewer",
    }
    result = await refiner.refine(raw, semaphore=semaphore)
    assert isinstance(result, CosmeticPatch)
    assert result.file_path == Path("src/strloc.py")
    # String-shaped location normalizes to {"file": ..., "line": 0},
    # so the line range is (max(1, -1), 1) = (1, 1).
    assert result.line_range == (1, 1)
    assert "trim trailing whitespace" in result.rationale


@pytest.mark.asyncio
async def test_refiner_accepts_none_location():
    """A missing/`None` `location` must not crash `refine`.

    Same crash class as the bare-string case; the refiner treats both
    as 'no location known' and produces a CosmeticPatch with a
    default-range and the raw text as the rationale.
    """
    refiner = CosmeticRefiner(model="test")
    semaphore = asyncio.Semaphore(1)
    raw = {
        "sub_bid": "00000-003",
        "text": "refactor the for loop",
        "location": None,
        "proposed_by": "IncrementQualityReviewer",
    }
    result = await refiner.refine(raw, semaphore=semaphore)
    assert isinstance(result, CosmeticPatch)
    # None → {} → file_path=None, line=1 (default), range=(1, 2).
    assert result.line_range == (1, 2)


@pytest.mark.asyncio
async def test_refiner_dict_location_still_works():
    """Sanity: the documented dict shape continues to work after the fix."""
    refiner = CosmeticRefiner(model="test")
    semaphore = asyncio.Semaphore(1)
    raw = {
        "sub_bid": "00000-004",
        "text": "extract magic number",
        "location": {"file": "src/d.py", "line": 7},
        "proposed_by": "IncrementQualityReviewer",
    }
    result = await refiner.refine(raw, semaphore=semaphore)
    assert result.file_path == Path("src/d.py")
    # line_range is centered around line 7: (7-1, 7+1) = (6, 8).
    assert result.line_range == (6, 8)
