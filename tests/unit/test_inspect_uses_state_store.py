"""Inspect artifact + verdict + settle report I/O uses StateStore (P32 task 12).

The pre-migration paths were ``<project_dir>/.mage/inspect/...``,
``<project_dir>/.mage/verdicts/...``, and ``<project_dir>/.mage/settle/...``.
After P32, those artifacts live on the orphan branch at ``inspect/...``,
``verdicts/...``, and ``settle/...`` (relative paths), written via the
:class:`mage.state_store.StateStore`. This module pins the path
conventions:

- ``inspect/<feature_id>/<iteration>.yaml`` round-trips through
  ``StateStore.write``/``read``.
- ``verdicts/<draft_hash>/<dimension>.yaml`` round-trips the same way.
- ``settle/<feature_id>.md`` round-trips the same way.

The full ``InspectArtifact.finalize_to_state_store`` /
``InspectArtifact.load_from_state_store`` /
``VerdictArtifact.finalize_to_state_store`` API surface is exercised
end-to-end in :mod:`tests.unit.test_inspect` and friends — this module
is the cheap path-convention smoke test that the brief asks for.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mage.state_store import StateStore


def _git_repo(path: Path) -> Path:
    """Initialize a git repo at ``path`` with identity configured."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def test_inspect_artifact_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    store = StateStore(repo, "feature-artifacts", identity=("T", "t@e"))
    path = "inspect/feature_a/0.yaml"
    store.write(path, b"finding: yes\n")
    assert store.read(path) == b"finding: yes\n"


def test_verdict_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    store = StateStore(repo, "feature-artifacts", identity=("T", "t@e"))
    path = "verdicts/abc123/spec_compliance.yaml"
    store.write(path, b"verdict: pass\n")
    assert store.read(path) == b"verdict: pass\n"


def test_settle_report_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    store = StateStore(repo, "feature-artifacts", identity=("T", "t@e"))
    path = "settle/feature_a.md"
    store.write(path, b"# Settle\n")
    assert store.read(path) == b"# Settle\n"


@pytest.mark.asyncio
async def test_cross_scenario_receives_state_store(tmp_path: Path, state_store) -> None:
    """InspectFeatureStage passes ``state_store`` to the ``cross_scenario`` reviewer (P32 task 12 fix).

    The per-scenario reviewer call (lines 251-259) already passes
    ``state_store=context.state_store``. The cross-scenario call (around
    line 335) was missing it. Without it, ``ReviewerAgent.run`` falls
    through to ``VerdictArtifact.finalize(Path(verdict_path), ...)``,
    which resolves a relative ``verdict_path`` (e.g.
    ``verdicts/<fid>/cross_scenario.yaml``) against the cwd and silently
    writes the verdict to the working tree instead of the orphan branch.

    This test pins the cross-scenario call site to also pass
    ``state_store`` so a real ``CrossScenarioReviewer`` can persist its
    verdict through the orphan branch (the migration's
    source-of-truth).
    """

    from datetime import UTC, datetime

    from mage.artifacts.mapping import MappingArtifact
    from mage.artifacts.verdict import ReviewerVerdict
    from mage.orchestration.events import EventsLog
    from mage.orchestration.inspect_feature import InspectFeatureStage
    from mage.orchestration.nodes import PipelineContext
    from mage.verification.host_overrides import HostConfig

    class _CleanMechanicalVerifier:
        def verify(self, draft, mapping):
            return []

    events_log = EventsLog(tmp_path / "events.jsonl")
    context = PipelineContext(
        state_store=state_store,
        project_dir=tmp_path,
        mapping=MappingArtifact(project_id="feat-1"),
        events_log=events_log,
        plan_path=tmp_path / "plan.md",
        iteration=0,
    )

    captured_kwargs: list[dict] = []

    class _CapturingReviewer:
        dimension = "cross_scenario"

        async def run(self, **kwargs) -> ReviewerVerdict:  # type: ignore[no-untyped-def]
            captured_kwargs.append(kwargs)
            return ReviewerVerdict(
                dimension=self.dimension,
                outcome="pass",
                draft_hash="",
                reviewed_at=datetime.now(UTC),
                reviewer_id=f"{self.dimension}@v1",
                findings=[],
            )

    stage = InspectFeatureStage(
        context.events_log,
        reviewers=[_CapturingReviewer()],
        mechanical_verifier=_CleanMechanicalVerifier(),
        host_config=HostConfig(),
    )

    scenario = {
        "sub_bid": "000000",
        "base_bid": "00000",
        "scenario_name": "happy",
        "gherkin_body": "Given a user\nWhen they act\nThen it succeeds",
        "tags": ["@status-live"],
    }

    await stage.run_pass(
        context,
        feature_id="feat-cross",
        scenarios=[scenario],
    )

    assert captured_kwargs, "cross_scenario reviewer was never invoked"
    cross_call = captured_kwargs[-1]
    assert "state_store" in cross_call, (
        "cross_scenario reviewer call is missing state_store kwarg; "
        "InspectFeatureStage must pass state_store=context.state_store "
        "to mirror the per-scenario call site"
    )
    assert cross_call["state_store"] is state_store, (
        "cross_scenario reviewer received a state_store that is not the "
        "context's StateStore; would fall through to working-tree finalize"
    )
