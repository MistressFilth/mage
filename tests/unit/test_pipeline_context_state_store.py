"""PipelineContext must carry a StateStore field (P32)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from mage.artifacts.mapping import MappingArtifact
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext
from mage.state_store import StateStore


def _full_kwargs(project_dir: Path) -> dict:
    """Build the required mapping/events_log fields for a valid construction."""
    return {
        "mapping": MappingArtifact(schema_version=2, project_id="p", base_bids=[]),
        "events_log": EventsLog(project_dir / "events.jsonl"),
    }


def test_pipeline_context_requires_state_store(tmp_path: Path) -> None:
    """PipelineContext cannot be constructed without state_store."""
    kwargs = _full_kwargs(tmp_path)
    with pytest.raises(ValidationError):
        PipelineContext(project_dir=tmp_path, **kwargs)


def test_pipeline_context_accepts_state_store(tmp_path: Path, state_store) -> None:
    store = StateStore(
        tmp_path, "feature-artifacts", identity=("T", "t@e"), command_runner=MagicMock()
    )
    kwargs = _full_kwargs(tmp_path)
    ctx = PipelineContext(project_dir=tmp_path, state_store=store, **kwargs)
    assert ctx.state_store is store


def test_pipeline_context_state_store_is_frozen(tmp_path: Path, state_store) -> None:
    store = StateStore(
        tmp_path, "feature-artifacts", identity=("T", "t@e"), command_runner=MagicMock()
    )
    kwargs = _full_kwargs(tmp_path)
    ctx = PipelineContext(project_dir=tmp_path, state_store=store, **kwargs)
    with pytest.raises((ValidationError, AttributeError)):
        ctx.state_store = store
