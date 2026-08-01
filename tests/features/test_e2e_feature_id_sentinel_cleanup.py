"""End-to-end + static guard for Plan 13 (feature_id sentinel cleanup).

Plan 13 removed three ``feature_id="unknown"`` literals from the
inspect-feature and inscribe paths. This module pins that cleanup with two
tests:

1. **Static guard** — grep the two source files for the exact sentinel
   patterns the plan banned (``"feature_id": "unknown"`` as a JSON-shaped
   payload value, and ``append_cosmetic("unknown"...`` as the first arg to
   :func:`append_cosmetic`). The sub_bid/scenario_name ``"unknown"``
   fallbacks in ``inspect_feature.py`` are explicitly out of scope per the
   spec and are NOT flagged.
2. **End-to-end** — drive ``InscribeStage`` and ``InspectFeatureStage``
   through the Python API with a real ``feature_id`` and verify that:
     - no ``INSCRIBE_*`` event payload carries ``feature_id="unknown"``
     - no cosmetic-queue entry produced by ``_append_cosmetics`` carries
       ``feature_id="unknown"``

The E2E test is intentionally driven via the Python API (mirroring
``tests/features/test_e2e_inspect_settle.py`` and
``tests/features/test_e2e_inscribe.py``) rather than spawning the ``mage``
binary, so the test is fast and isolated.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from mage.agents.inscribe import InscribeAgent, InscribeOutput, ScenarioSpec
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.verdict import ReviewerFinding, ReviewerVerdict
from mage.orchestration.events import EventsLog
from mage.orchestration.inscribe import InscribeStage
from mage.orchestration.inspect_feature import InspectFeatureStage
from mage.orchestration.nodes import PipelineContext
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import MechanicalVerifier
from mage.verification.reviewers.determinism import DeterminismReviewer
from mage.verification.reviewers.lifecycle_tags import LifecycleTagsReviewer
from mage.verification.reviewers.naming_idiom import NamingIdiomReviewer
from mage.verification.reviewers.scenario_clarity import ScenarioClarityReviewer
from mage.verification.reviewers.spec_compliance import SpecComplianceReviewer
from mage.verification.reviewers.step_grammar import StepGrammarReviewer
from mage.verification.reviewers.testability import TestabilityReviewer

# ---------------------------------------------------------------------------
# Static guard
# ---------------------------------------------------------------------------

# Plan 13 banned exactly two patterns in the inspect-feature and inscribe
# paths. The sub_bid/scenario_name "unknown" fallbacks are explicitly out of
# scope per the spec and MUST NOT be flagged by this guard.
#
# Patterns are evaluated via Python ``re.search`` so the guard catches both
# the single-line ``append_cosmetic("unknown", ...)`` form AND a future
# regression that wraps the call across lines like
# ``append_cosmetic(\n    "unknown", ...``. ``re.DOTALL`` lets whitespace
# match newlines.
_BANNED_PATTERNS: tuple[str, ...] = (
    r'"feature_id"\s*:\s*"unknown"',
    r'append_cosmetic\s*\(\s*"unknown"',
)


def _banned_patterns_target_files() -> tuple[str, ...]:
    repo_root = Path(__file__).resolve().parents[2]
    return (
        str(repo_root / "src/mage/orchestration/inspect_feature.py"),
        str(repo_root / "src/mage/orchestration/inscribe.py"),
    )


def test_static_guard_no_unknown_feature_id_in_inspect_or_inscribe_source() -> None:
    """The banished sentinel patterns stay gone after the Plan 13 cleanup.

    Catches the two patterns the plan explicitly banned, regardless of
    surrounding whitespace (including across newlines):
    - ``"feature_id": "unknown"`` as a payload/dict value
    - ``append_cosmetic("unknown"`` as the first positional argument
      (also wrapped-across-lines form)

    Sub_bid/scenario_name ``"unknown"`` fallbacks are intentionally out of
    scope and are NOT flagged here.
    """
    target_files = _banned_patterns_target_files()

    offenders: list[tuple[str, str, int, str]] = []  # (pattern, file, lineno, line)
    for pattern in _BANNED_PATTERNS:
        compiled = re.compile(pattern, re.DOTALL)
        for path_str in target_files:
            path = Path(path_str)
            text = path.read_text()
            match = compiled.search(text)
            if match is None:
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            line = text.splitlines()[line_no - 1]
            offenders.append((pattern, str(path), line_no, line))

    assert not offenders, (
        "Static guard failed: banned sentinel reappeared in inspect_feature.py "
        "or inscribe.py:\n"
        + "\n".join(f"{p}  {f}:{n}: {l!r}" for (p, f, n, l) in offenders)
    )


# ---------------------------------------------------------------------------
# End-to-end: drive stages via Python API; assert no event payload or
# cosmetic-queue entry carries feature_id="unknown".
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_test_model() -> None:
    """Force Pydantic-AI agents to use TestModel for deterministic tests."""
    models.ALLOW_MODEL_REQUESTS = False


def _make_pass_reviewer(reviewer_cls, dimension: str):
    """Build a reviewer with a canned pass ReviewerVerdict for TestModel."""
    canned = ReviewerVerdict(
        dimension=dimension,
        outcome="pass",
        draft_hash="x",
        reviewed_at=datetime.now(UTC),
        reviewer_id=f"{dimension}@v1",
        findings=[],
        notes="",
    )
    return reviewer_cls(model=TestModel(custom_output_args=canned))


def _all_seven_pass_reviewers() -> list:
    return [
        _make_pass_reviewer(SpecComplianceReviewer, "spec_compliance"),
        _make_pass_reviewer(ScenarioClarityReviewer, "scenario_clarity"),
        _make_pass_reviewer(StepGrammarReviewer, "step_grammar"),
        _make_pass_reviewer(TestabilityReviewer, "testability"),
        _make_pass_reviewer(DeterminismReviewer, "determinism"),
        _make_pass_reviewer(NamingIdiomReviewer, "naming_idiom"),
        _make_pass_reviewer(LifecycleTagsReviewer, "lifecycle_tags"),
    ]


def _canned_inscribe_output() -> InscribeOutput:
    return InscribeOutput(
        scenarios=[
            ScenarioSpec(
                name="login succeeds",
                gherkin_body=(
                    "Given a user with valid credentials\n"
                    "When they attempt to log in\n"
                    "Then they are authenticated"
                ),
            ),
        ]
    )


async def _seed_minimal_project(project_dir: Path, feature_id: str) -> MappingArtifact:
    """Write behaviors.yaml + mapping.yaml on disk for the given feature_id."""
    (project_dir / "behaviors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "feature_id": feature_id,
                "enumerated_at": "2026-07-28T00:00:00Z",
                "behaviors": [
                    {
                        "id": "00000",
                        "name": "authenticate-user",
                        "description": "User logs in",
                        "depends_on": [],
                        "notes": "",
                        "cross_behavior_links": [],
                    }
                ],
            }
        )
    )
    mapping = MappingArtifact(
        project_id="e2e",
        base_bids=[
            {
                "base_bid": "00000",
                "behavior_name": "authenticate-user",
                "behavior_description": "User logs in",
                "depends_on": [],
                "notes": "",
                "scenarios": [],
                "reversion_log": [],
                "post_live_revisions": [],
                "cross_behavior_links": [],
            }
        ],
    )
    await mapping.save(project_dir / "mapping.yaml")
    return mapping


def _make_minor_reviewer(dimension: str):
    """Return a reviewer that emits a minor finding every call — drives
    cosmetics into the queue via InspectFeature._append_cosmetics."""

    async def _run(self, **kwargs):
        return ReviewerVerdict(
            dimension=dimension,
            outcome="fail",
            draft_hash="x",
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{dimension}@v1",
            findings=[
                ReviewerFinding(
                    id="m-1",
                    severity="minor",
                    location="src/example.py:1",
                    issue="Rephrase for clarity",
                    rationale="Cosmetic",
                    suggestion="Rephrase",
                    citations=["00000-0"],
                )
            ],
        )

    return type(
        f"MinorReviewer_{dimension}",
        (),
        {"dimension": dimension, "run": _run},
    )()


def _make_pass_duck_reviewer(dimension: str):
    """Return a reviewer-shaped duck that emits a clean pass verdict."""

    async def _run(self, **kwargs):
        return ReviewerVerdict(
            dimension=dimension,
            outcome="pass",
            draft_hash="x",
            reviewed_at=datetime.now(UTC),
            reviewer_id=f"{dimension}@v1",
            findings=[],
        )

    return type(
        f"PassDuckReviewer_{dimension}",
        (),
        {"dimension": dimension, "run": _run},
    )()


@pytest.mark.asyncio
async def test_e2e_run_inscribe_and_inspect_never_emit_unknown_feature_id(
    tmp_path: Path,
):
    """Drive Inscribe + InspectFeature through the Python API.

    Asserts that no ``INSCRIBE_*`` event payload nor any cosmetic-queue
    entry produced across the two stages carries ``feature_id="unknown"``.
    """
    feature_id = "feat-e2e-sentinel"
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    events_path = project_dir / "events.jsonl"
    log = EventsLog(events_path)
    await _seed_minimal_project(project_dir, feature_id=feature_id)

    mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    context = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
        feature_id=feature_id,
    )

    # --- InscribeStage: writes INSCRIBE_STARTED + INSCRIBE_COMPLETED events
    # with a real feature_id threaded from context.
    inscribe_stage = InscribeStage(
        events_log=log,
        agent=InscribeAgent(
            model=TestModel(custom_output_args=_canned_inscribe_output())
        ),
        host_config=HostConfig(max_iterations=3),
        reviewers=_all_seven_pass_reviewers(),
    )
    await inscribe_stage.run(context)

    # --- InspectFeatureStage: minor findings flow into cosmetic queue.
    # The first two reviewers emit minor findings; the rest pass.
    inspect_reviewers = [
        _make_minor_reviewer("spec_compliance"),
        _make_minor_reviewer("scenario_clarity"),
        _make_pass_reviewer(StepGrammarReviewer, "step_grammar"),
        _make_pass_reviewer(TestabilityReviewer, "testability"),
        _make_pass_reviewer(DeterminismReviewer, "determinism"),
        _make_pass_reviewer(NamingIdiomReviewer, "naming_idiom"),
        _make_pass_reviewer(LifecycleTagsReviewer, "lifecycle_tags"),
        _make_pass_duck_reviewer("cross_scenario"),
    ]
    inspect_stage = InspectFeatureStage(
        events_log=log,
        reviewers=inspect_reviewers,
        mechanical_verifier=MechanicalVerifier(checks=[]),
        host_config=HostConfig(),
    )
    artifact = await inspect_stage.run_pass(
        context,
        feature_id=feature_id,
        scenarios=[
            {
                "sub_bid": "00000-0",
                "scenario_name": "happy",
                "name": "happy",
                "gherkin_body": "Given a\nWhen b\nThen c",
            }
        ],
    )
    assert artifact.ready_to_merge is True

    # --- Assertions: nothing in the run carries feature_id="unknown".
    events_text = events_path.read_text()
    assert '"feature_id": "unknown"' not in events_text, (
        "Event payload still carries feature_id='unknown' after Inscribe + "
        "InspectFeature run:\n"
        f"{events_text}"
    )

    # Sanity: the events.jsonl must contain real INSCRIBE_* events with the
    # threaded feature_id.
    events = log.read_all()
    inscribe_events = [
        e
        for e in events
        if e.event_type.value in ("inscribe_started", "inscribe_completed")
    ]
    assert inscribe_events, "expected INSCRIBE_STARTED + INSCRIBE_COMPLETED events"
    for event in inscribe_events:
        payload_feature_id = event.payload.get("feature_id")
        assert payload_feature_id == feature_id, (
            f"event {event.event_type.value!r} carried feature_id="
            f"{payload_feature_id!r}; expected {feature_id!r}"
        )

    # Cosmetic queue entries (on disk via re-loaded mapping) must carry
    # the real feature_id, never "unknown".
    updated = MappingArtifact.load(project_dir / "mapping.yaml")
    queue = updated.feature_cosmetic_queue
    assert queue, "expected at least one cosmetic queue entry"
    for entry in queue:
        assert entry.get("feature_id") == feature_id, (
            f"cosmetic queue entry has feature_id={entry.get('feature_id')!r}; "
            f"expected {feature_id!r}"
        )
        assert entry.get("feature_id") != "unknown"
