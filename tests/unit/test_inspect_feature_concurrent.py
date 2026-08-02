"""InspectFeature per-scenario reviewer dispatch uses asyncio.Semaphore sized by host_config.max_concurrent_llm_calls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact
from mage.artifacts.verdict import ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.orchestration.inspect_feature import InspectFeatureStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig


def _ctx(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        project_dir=tmp_path,
        mapping=MappingArtifact(
            project_id="p",
            base_bids=[
                BaseBIDEntry(
                    base_bid="00000",
                    behavior_name="b",
                    behavior_description="d",
                ),
            ],
        ),
        events_log=EventsLog(tmp_path / "events.jsonl"),
    )


def _make_reviewer(dimension: str):
    class Reviewer:
        dimension: str = ""

        async def run(self, **kwargs):
            return ReviewerVerdict(
                dimension=dimension,
                outcome="pass",
                draft_hash="",
                reviewed_at=datetime.now(UTC),
                reviewer_id=f"{dimension}@v1",
                findings=[],
            )

    Reviewer.dimension = dimension
    return Reviewer()


class _MechanicalVerifier:
    def verify(self, draft, mapping):
        return []


@pytest.mark.asyncio
async def test_inspect_feature_stage_constructs_semaphore_with_max_concurrent_llm_calls(
    tmp_path: Path, monkeypatch
):
    """InspectFeature per-scenario dispatch must construct asyncio.Semaphore
    sized by host_config.max_concurrent_llm_calls."""
    ctx = _ctx(tmp_path)
    reviewers = [
        _make_reviewer("spec_compliance"),
        _make_reviewer("scenario_clarity"),
    ]
    stage = InspectFeatureStage(
        events_log=ctx.events_log,
        reviewers=reviewers,
        mechanical_verifier=_MechanicalVerifier(),
        host_config=HostConfig(max_concurrent_llm_calls=3),
    )

    semaphore_constructions: list[int] = []
    original = asyncio.Semaphore

    def recording_semaphore(value: int = 1, *args, **kwargs):
        semaphore_constructions.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(asyncio, "Semaphore", recording_semaphore)

    scenarios = [
        {
            "sub_bid": "00000-001",
            "name": "scenario_a",
            "gherkin_body": "Given a\nThen b",
        },
        {
            "sub_bid": "00000-002",
            "name": "scenario_b",
            "gherkin_body": "Given c\nThen d",
        },
    ]

    await stage._run_reviewers(
        ctx,
        feature_id="feat-1",
        scenarios=scenarios,
    )

    assert any(v == 3 for v in semaphore_constructions), (
        f"Expected Semaphore(3), got constructions: {semaphore_constructions}"
    )
