"""CLI entry point for the mage spec-driven development pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import MappingArtifact
from mage.artifacts.plan import PlanError
from mage.artifacts.verdict import VerdictError
from mage.cosmetic_pid import is_alive, pid_file_path, read_pid, remove_pid
from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import default_check_set, load_host_config
from mage.verification.mechanical import (
    MechanicalVerifier,
    ScenarioDraft,
)

if TYPE_CHECKING:
    from mage.orchestration.runner import FeatureRunner


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="mage",
        description="mage: spec-driven development pipeline",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # mage verify — run mechanical checks against a feature/scenario.
    verify = subparsers.add_parser(
        "verify", help="Run mechanical verification on a scenario"
    )
    verify.add_argument(
        "--feature", type=Path, required=True, help="Path to the .feature file"
    )
    verify.add_argument(
        "--scenario", required=True, help="Scenario name within the feature"
    )
    verify.add_argument("--sub-bid", required=True, help="Sub-BID for the scenario")
    verify.add_argument("--base-bid", required=True, help="Parent base-BID")

    # mage plan <subcommand>
    plan_parser = subparsers.add_parser("plan", help="Plan operations")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)

    # mage plan show
    plan_subparsers.add_parser("show", help="Display Plan + digest")

    # mage plan revise
    revise_parser = plan_subparsers.add_parser(
        "revise", help="Record a Plan revision after halt"
    )
    revise_parser.add_argument("--reason", type=str, required=True)
    revise_parser.add_argument("--approver", type=str, required=True)

    # mage run
    run_parser = subparsers.add_parser("run", help="Run the pipeline")
    run_parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    run_parser.add_argument("--dry-run", action="store_true", help="Use stub agents")
    run_parser.add_argument("--model", help="Override the LLM model identifier")

    # mage review <subcommand>
    review_parser = subparsers.add_parser("review", help="Review operations")
    review_subparsers = review_parser.add_subparsers(
        dest="review_command", required=True
    )
    review_subparsers.add_parser("show", help="Display latest aggregate verdict")

    # mage inspect <subcommand>
    inspect_parser = subparsers.add_parser("inspect", help="Inspect operations")
    inspect_subparsers = inspect_parser.add_subparsers(
        dest="inspect_command", required=True
    )

    # mage inspect show
    inspect_show_parser = inspect_subparsers.add_parser(
        "show", help="Display latest Inspect artifact"
    )
    inspect_show_parser.add_argument("feature_id")
    inspect_show_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )

    # mage settle <subcommand>
    settle_parser = subparsers.add_parser("settle", help="Settle operations")
    settle_subparsers = settle_parser.add_subparsers(
        dest="settle_command", required=True
    )

    # mage settle run
    settle_run_parser = settle_subparsers.add_parser(
        "run", help="Run SettleFeature for a feature"
    )
    settle_run_parser.add_argument("feature_id")
    settle_run_parser.add_argument(
        "--disposition",
        type=str,
        choices=["merged", "pr_opened", "kept", "discarded"],
        default=None,
        help="Non-interactive: choose merged|pr_opened|kept|discarded",
    )
    settle_run_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )

    # mage cosmetic <subcommand>
    cosmetic_parser = subparsers.add_parser(
        "cosmetic", help="Show/apply cosmetic items"
    )
    cosmetic_subparsers = cosmetic_parser.add_subparsers(
        dest="cosmetic_command", required=True
    )

    # mage cosmetic show
    cosmetic_show_parser = cosmetic_subparsers.add_parser(
        "show", help="Show refined cosmetic items for a feature"
    )
    cosmetic_show_parser.add_argument("feature_id")
    cosmetic_show_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )
    cosmetic_show_parser.add_argument(
        "--raw",
        action="store_true",
        help="Dump queue entries without LLM refinement",
    )
    cosmetic_show_parser.add_argument(
        "--journal",
        action="store_true",
        help="Append a section of inspect journal entries for the feature",
    )
    cosmetic_show_parser.add_argument(
        "--filter",
        action="append",
        default=None,
        help="Restrict to sub_bids matching the predicate, e.g. 'sub_bid=01JF...'",
    )

    # mage cosmetic list
    cosmetic_list_parser = cosmetic_subparsers.add_parser(
        "list",
        help="List cosmetic queue entries for a feature",
    )
    cosmetic_list_parser.add_argument("feature_id")
    cosmetic_list_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )
    cosmetic_list_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default text)",
    )
    cosmetic_list_parser.add_argument(
        "--filter",
        action="append",
        default=None,
        help="Restrict to sub_bids matching 'sub_bid=...'",
    )

    # mage cosmetic apply
    cosmetic_apply_parser = cosmetic_subparsers.add_parser(
        "apply", help="Apply cosmetic items to the feature branch"
    )
    cosmetic_apply_parser.add_argument("feature_id")
    cosmetic_apply_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )
    cosmetic_apply_parser.add_argument(
        "--dry-run", action="store_true", help="Skip file writes + commits"
    )
    cosmetic_apply_parser.add_argument(
        "--model",
        help=(
            "Override the LLM model identifier (use 'test' for the "
            "Pydantic-AI TestModel stub)"
        ),
    )

    # mage cosmetic watch
    cosmetic_watch_parser = cosmetic_subparsers.add_parser(
        "watch",
        help="Long-running daemon that auto-applies cosmetic queue items",
    )
    cosmetic_watch_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )
    cosmetic_watch_parser.add_argument("--poll-interval-ms", type=int, default=250)

    # mage cosmetic unwatch
    cosmetic_unwatch_parser = cosmetic_subparsers.add_parser(
        "unwatch",
        help="Stop the cosmetic watcher daemon (per-project)",
    )
    cosmetic_unwatch_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )
    cosmetic_unwatch_parser.add_argument(
        "--force",
        action="store_true",
        help="Escalate to SIGKILL after a 5s SIGTERM timeout",
    )

    # mage mapping
    mapping_parser = subparsers.add_parser(
        "mapping", help="Mapping artifact operations"
    )
    mapping_subparsers = mapping_parser.add_subparsers(
        dest="mapping_command", required=True
    )
    mapping_save_parser = mapping_subparsers.add_parser(
        "save", help="Re-save mapping.yaml and emit MAPPING_SAVED"
    )
    mapping_save_parser.add_argument(
        "--project-dir", type=Path, default=argparse.SUPPRESS
    )

    return parser


class _StubEtchAgent:
    """Returns one trivial RedTestSpec per call. Used in --dry-run mode."""

    async def run(self, *, step: str, scenario_context: dict):
        from mage.agents.etch import RedTestSpec

        return RedTestSpec(
            step_name=step,
            test_path=f"tests/{step}.py",
            test_code=f"def test_{step}(): pass\n",
        )


class _StubRealizeAgent:
    """Returns no file changes and a stub summary. Used in --dry-run mode."""

    def __init__(self, system_prompt_only: bool = True) -> None:
        from mage.agents.realize import RealizeAgent

        self._inner = RealizeAgent(model=None, system_prompt_only=system_prompt_only)

    async def run(self, **kwargs):
        from mage.agents.realize import RealizeOutput

        return RealizeOutput(files_changed=[], summary="(dry-run)")


class _StubIncrementQualityReviewer:
    """Returns a clean verdict. Used in --dry-run mode."""

    async def run(self, **kwargs) -> object:
        from pydantic import BaseModel, ConfigDict

        class _V(BaseModel):
            model_config = ConfigDict(frozen=True)

            dimension: str = "increment_quality"
            findings: list = []

        return _V()


class _NoopMechanicalVerifier:
    def verify(self, *, scope: str) -> list:
        return []


class _StubStageNode(StageNode):
    """No-op stage used in --dry-run mode.

    Emits STAGE_STARTED and STAGE_COMPLETED events like a real StageNode but
    performs no work. Stands in for stages whose real wiring (decomposition,
    inscribe, inspect_feature, settle_feature) lives in Plan 9 and would
    otherwise reject an empty project.
    """

    def __init__(self, events_log: EventsLog, name: str) -> None:
        self.events_log = events_log
        self.name = name

    async def _run(self, context: PipelineContext) -> PipelineContext:
        return context


def _make_dry_run_runner(
    log,
    host_config,
    *,
    feature_id: str = "",
) -> FeatureRunner:
    """Construct a FeatureRunner wired with stub agents for --dry-run mode."""
    from mage.orchestration.etch import EtchStage
    from mage.orchestration.inspect_loop import InspectLoopStage
    from mage.orchestration.realize import RealizeStage
    from mage.orchestration.runner import FeatureRunner

    etch = EtchStage(log, agent=_StubEtchAgent())  # type: ignore[arg-type, ty:invalid-argument-type]
    realize = RealizeStage(
        log,
        agent=_StubRealizeAgent(),  # type: ignore[arg-type, ty:invalid-argument-type]
        host_config=host_config,
    )
    inspect = InspectLoopStage(
        log,
        mechanical_verifier=_NoopMechanicalVerifier(),
        increment_quality_reviewer=_StubIncrementQualityReviewer(),
        host_config=host_config,
    )
    return FeatureRunner(
        etch=etch,
        realize=realize,
        inspect_loop=inspect,
        per_loop_max_iterations=host_config.per_loop_max_iterations,
        feature_id=feature_id,
    )


def _make_dry_run_stages(log, host_config):
    """Build the full pipeline stages list in --dry-run mode.

    Real-agent stages (decomposition, inscribe, inspect_feature,
    settle_feature) are replaced by no-op _StubStageNode instances because
    their real wiring lives in Plan 9. The automation stage uses the real
    AutomationStage with a stubbed FeatureRunner, so a project with no
    approved scenarios runs cleanly.
    """
    from mage.orchestration.automation import AutomationStage

    runner = _make_dry_run_runner(log, host_config)
    return [
        _StubStageNode(log, "decomposition"),
        _StubStageNode(log, "inscribe"),
        AutomationStage(log, runner=runner),
        _StubStageNode(log, "inspect_feature"),
        _StubStageNode(log, "settle_feature"),
    ]


async def cmd_plan_show(args):
    """Display Plan + digest + last event."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    plan_path = project_dir / "plan.md"
    log = (
        EventsLog(project_dir / "events.jsonl")
        if (project_dir / "events.jsonl").exists()
        else None
    )

    print(f"Plan: {plan_path}")

    if not plan_path.exists():
        print("(Plan file does not exist on disk)")
        return 0

    # Find latest FINALIZED/REVISED event
    events = log.read_all() if log is not None else []
    plan_events = [
        e
        for e in events
        if e.event_type.value in ("plan_finalized", "plan_revised")
        and e.payload.get("plan_path") == str(plan_path)
    ]
    if not plan_events:
        print("(No PLAN_FINALIZED event — Plan is unfinalized)")
        return 0

    latest = max(plan_events, key=lambda e: e.timestamp)
    digest = latest.payload.get("plan_sha256") or latest.payload.get("new_sha256")
    print(f"Digest: {digest}")
    print(
        f"Last event: {latest.event_type.value.upper().replace('_', ' ')} at {latest.timestamp.isoformat()}"
    )
    print()

    assert log is not None
    try:
        content = await PlanArtifact.load(plan_path, log)
    except (PlanError, OSError) as e:
        print(f"(Failed to load Plan: {e})")
        return 0

    lines = content.splitlines()
    preview = "\n".join(lines[:50])
    print(preview)
    if len(lines) > 50:
        print(f"\n... ({len(lines) - 50} more lines)")
    return 0


async def cmd_plan_revise(args):
    """Record a Plan revision after halt."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    plan_path = project_dir / "plan.md"

    if not plan_path.exists():
        print(
            f"mage plan revise: error: plan.md not found at {plan_path}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Check that a prior finalization exists
    events = log.read_all()
    plan_events = [
        e
        for e in events
        if e.event_type.value in ("plan_finalized", "plan_revised")
        and e.payload.get("plan_path") == str(plan_path)
    ]
    if not plan_events:
        print(
            f"mage plan revise: error: no PLAN_FINALIZED event for {plan_path}; "
            f"run mage run to create the Plan first",
            file=sys.stderr,
        )
        sys.exit(2)

    new_digest = PlanArtifact._compute_digest(plan_path.read_text(encoding="utf-8"))
    latest = max(plan_events, key=lambda e: e.timestamp)
    recorded = latest.payload.get("plan_sha256") or latest.payload.get("new_sha256")
    if new_digest == recorded:
        print(
            "mage plan revise: warning: Plan digest unchanged; recording anyway",
            file=sys.stderr,
        )

    new_digest = await PlanArtifact.revise(
        plan_path,
        plan_path.read_text(encoding="utf-8"),
        reason=args.reason,
        human_approver=args.approver,
        events_log=log,
    )

    print(f"Plan revision recorded. New digest: {new_digest}")
    print("Restart the pipeline with: mage run")
    return 0


async def cmd_run(args):
    """Run the pipeline with halt handling and resume support."""
    from mage.orchestration.graph import PipelineGraph
    from mage.orchestration.persistence import FileStatePersistence

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    state_dir = project_dir / ".haileris" / "state"

    mapping_path = project_dir / "mapping.yaml"
    if mapping_path.exists():
        # Brief had MappingArtifact.load(mapping_path, log) but the actual
        # signature is load(path) — drop the spurious log kwarg.
        mapping = MappingArtifact.load(mapping_path)
    else:
        mapping = MappingArtifact(
            schema_version=2, project_id=project_dir.name, base_bids=[]
        )

    persistence = FileStatePersistence(state_dir=state_dir, state_type=PipelineContext)
    saved = persistence.load_state()
    initial_context = saved or PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
        iteration=0,
    )

    host_config = load_host_config(project_dir)
    if getattr(args, "model", None):
        host_config = host_config.model_copy(update={"model": args.model})
    initial_context.host_config = host_config

    # Plan 9: stages are the same wiring for both --dry-run and real mode.
    # The agent substitution (stub vs Pydantic-AI) is driven by whether
    # host_config.model is set. `--dry-run` on `mage run` is a no-op kept
    # for backward compatibility; the same flag still controls whether
    # `mage cosmetic apply` writes files / commits.
    stages = _make_dry_run_stages(log, host_config)

    graph = PipelineGraph(stages=stages, events_log=log)
    try:
        await graph.run(initial_context)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 — top-level CLI guard
        print(f"mage run: error: {error}", file=sys.stderr)
        return 1
    print(f"mage run: complete for {project_dir}")
    return 0


async def cmd_review_show(args):
    """Display the latest aggregate verdict for the project."""
    from mage.artifacts.verdict import ReviewerAggregate, VerdictArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")

    events = log.read_all()
    aggregate_events = [
        e for e in events if e.event_type.value == "review_aggregate_recorded"
    ]
    if not aggregate_events:
        print(
            f"mage review show: no aggregate verdicts found in {project_dir}",
            file=sys.stderr,
        )
        sys.exit(2)

    latest = max(aggregate_events, key=lambda e: e.timestamp)
    digest = latest.payload.get("verdict_sha256")

    # C4: read the decision from the AGGREGATE file on disk (single source
    # of truth) rather than relying on the event payload, which the
    # VerdictArtifact schema doesn't include. The verdict_path in the
    # payload points to the aggregate.yaml we wrote.
    aggregate_path_str = latest.payload.get("verdict_path")
    decision = None
    if aggregate_path_str:
        aggregate_path = Path(aggregate_path_str)
        try:
            aggregate = await VerdictArtifact.load(aggregate_path, log)
            decision = ReviewerAggregate.model_validate(aggregate).decision
        except (VerdictError, OSError) as e:
            print(
                f"mage review show: warning: failed to read aggregate at "
                f"{aggregate_path}: {e}",
                file=sys.stderr,
            )

    print("Latest aggregate verdict:")
    print(f"  Path:       {aggregate_path_str}")
    print(f"  Digest:     {digest}")
    print(f"  Decision:   {decision}")
    print(f"  Recorded:   {latest.timestamp.isoformat()}")
    return 0


async def cmd_inspect_show(args):
    """Display the latest Inspect artifact for a feature."""
    from mage.artifacts.inspect import InspectArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    inspect_dir = project_dir / ".haileris" / "inspect" / args.feature_id
    if not inspect_dir.exists():
        print(f"No inspect directory for feature {args.feature_id!r}", file=sys.stderr)
        return 1

    # Find the highest iteration
    candidates = sorted(inspect_dir.glob("*.yaml"))
    if not candidates:
        print(f"No inspect artifacts for feature {args.feature_id!r}", file=sys.stderr)
        return 1
    latest = candidates[-1]

    content = await InspectArtifact.load(latest, log)
    print(f"# Inspect Feature {content.feature_id}")
    print(f"iteration: {content.iteration}/{content.eof_max_iterations}")
    print(f"ready_to_merge: {content.ready_to_merge}")
    print(f"scenarios: {len(content.scenarios)}")
    print(
        f"critical: {len(content.critical)}, important: {len(content.important)}, "
        f"minor: {len(content.minor)}"
    )
    print(f"cross_scenario findings: {len(content.cross_scenario)}")
    if content.ledger_markdown:
        print("\n## Ledger\n")
        print(content.ledger_markdown)
    return 0


async def cmd_settle_run(args):
    """Run SettleFeature for a feature. Interactive mode prompts for 4-option menu."""
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.settle_feature import SettleError, SettleFeatureStage

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")

    # Load mapping (default to empty if missing — matches cmd_verify pattern).
    mapping_path = project_dir / "mapping.yaml"
    if mapping_path.exists():
        mapping = MappingArtifact.load(mapping_path)
    else:
        mapping = MappingArtifact(
            schema_version=2,
            project_id=project_dir.name,
            base_bids=[],
        )

    ctx = PipelineContext(
        project_dir=project_dir,
        mapping=mapping,
        events_log=log,
        plan_path=project_dir / "plan.md",
        iteration=0,
    )

    valid_dispositions = ("merged", "pr_opened", "kept", "discarded")
    disposition = args.disposition

    if disposition is None:
        # Interactive mode: 4-option menu.
        print("Choose a disposition:")
        print("  1. Merge to the base branch locally")
        print("  2. Push the branch and create a pull request")
        print("  3. Keep the branch as-is")
        print("  4. Discard the branch")
        choice = input("Enter choice (1-4): ")
        menu = {"1": "merged", "2": "pr_opened", "3": "kept", "4": "discarded"}
        if choice not in menu:
            print(f"Invalid choice {choice!r}", file=sys.stderr)
            sys.exit(2)
        disposition = menu[choice]

    # argparse `choices=` already validates non-interactive values, but be
    # explicit in case the function is called programmatically.
    if disposition not in valid_dispositions:
        print(
            f"mage settle run: error: invalid disposition {disposition!r}; "
            f"must be one of {list(valid_dispositions)}",
            file=sys.stderr,
        )
        sys.exit(2)

    if disposition == "discarded":
        confirm = input("Type 'discard' to confirm: ")
        if confirm != "discard":
            print("Discard cancelled", file=sys.stderr)
            sys.exit(2)

    stage = SettleFeatureStage(
        log,
        host_config=load_host_config(project_dir),
    )
    try:
        await stage.run_settle(ctx, feature_id=args.feature_id, disposition=disposition)
    except (SettleError, ValueError) as error:
        print(f"mage settle run: error: {error}", file=sys.stderr)
        return 1
    print(f"Settle complete for {args.feature_id}: {disposition}")
    return 0


async def cmd_cosmetic_show(args) -> int:
    """Show cosmetic queue entries for a feature.

    Default mode refines via the LLM as before. `--raw` skips refinement
    and emits a stable text dump. `--journal` appends inspect journal
    entries for the same feature. `--filter sub_bid=...` narrows.
    """
    from mage.artifacts.cosmetic_state import load_state
    from mage.artifacts.mapping import MappingArtifact
    from mage.cosmetic_filters import FilterParseError, parse_filters

    project_dir: Path = getattr(args, "project_dir", Path.cwd())
    mapping_path = project_dir / "mapping.yaml"
    if not mapping_path.exists():
        print(
            f"mage cosmetic show: no mapping found at {mapping_path}", file=sys.stderr
        )
        return 1
    mapping = MappingArtifact.load(mapping_path)
    raw_filter = getattr(args, "filter", None)
    try:
        filters = parse_filters(raw_filter, subcommand="cosmetic show")
    except FilterParseError as e:
        print(
            f"mage cosmetic show: {e.message}",
            file=sys.stderr,
        )
        return 2
    queue = [
        q for q in mapping.cosmetic_findings if q.get("feature_id") == args.feature_id
    ]
    if "sub_bid" in filters:
        allowed = filters["sub_bid"]
        available = {q["sub_bid"] for q in queue}
        missing = allowed - available
        if missing:
            print(
                f"mage cosmetic show: unknown sub_bid "
                f"{min(missing)!r} for feature {args.feature_id!r}",
                file=sys.stderr,
            )
            return 2
        queue = [q for q in queue if q["sub_bid"] in allowed]
    queue.sort(key=lambda q: q.get("sub_bid", ""))
    state = load_state(project_dir)
    if getattr(args, "raw", False):
        for q in queue:
            sub_bid = q.get("sub_bid", "")
            applied = state.applied.get(sub_bid)
            status = "applied" if applied is not None else "pending"
            print(f"[sub_bid: {sub_bid}]")
            print(f"  scenario: {q.get('scenario_name', '—')}")
            print(f"  location: {q.get('location') or '—'}")
            print(f"  text: {q.get('text', '')}")
            print(f"  proposed_by: {q.get('proposed_by', '—')}")
            print(f"  feature_id: {q.get('feature_id', '—')}")
            print(f"  status: {status}")
        if getattr(args, "journal", False):
            _render_journal_section(
                project_dir=project_dir,
                feature_id=args.feature_id,
                mapping=mapping,
            )
        return 0
    if not queue:
        print(
            f"mage cosmetic show: no items for feature_id={args.feature_id}",
            file=sys.stderr,
        )
        if getattr(args, "journal", False):
            _render_journal_section(
                project_dir=project_dir,
                feature_id=args.feature_id,
                mapping=mapping,
            )
        return 0
    from mage.agents.cosmetic_refiner import CosmeticRefiner

    host_config = load_host_config(project_dir)
    refiner = CosmeticRefiner(model=host_config.model)
    semaphore = asyncio.Semaphore(host_config.max_concurrent_llm_calls)
    refined = await asyncio.gather(
        *[refiner.refine(q, semaphore=semaphore) for q in queue]
    )
    for item in refined:
        fp = str(item.file_path) if item.file_path else "<unresolved>"
        print(
            f"{item.sub_bid} {fp}:{item.line_range[0]}-{item.line_range[1]} "
            f"{item.rationale}"
        )
    if getattr(args, "journal", False):
        _render_journal_section(
            project_dir=project_dir,
            feature_id=args.feature_id,
            mapping=mapping,
        )
    return 0


def _render_journal_section(*, project_dir: Path, feature_id: str, mapping) -> None:
    """Print inspect journal entries tagged with `feature_id`, newest first."""
    by_sub = mapping.inspect_journal or {}
    flat: list[dict] = []
    for entries in by_sub.values():
        for entry in entries:
            if entry.get("feature_id") == feature_id:
                flat.append(entry)
    if not flat:
        return
    flat.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    print("## Inspect journal")
    print(f"[count: {len(flat)}, latest first]")
    print()
    for entry in flat:
        ts = entry.get("timestamp", "")
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        print(
            f"  {ts}  scenario={entry.get('scenario_id', '')} "
            f" iter={entry.get('iteration', '')} "
            f" dimension={entry.get('dimension', '')} "
            f" severity={entry.get('severity', '')}"
        )
        route = entry.get("route", "")
        finding_id = entry.get("finding_id", "")
        if route or finding_id:
            print(f"    route={route}  finding_id={finding_id}")
        loc = entry.get("location") or "null"
        print(f"    location={loc}")
        print(f"    issue: {entry.get('issue', '')}")
        print(f"    rationale: {entry.get('rationale', '')}")


async def cmd_cosmetic_apply(args) -> int:
    """CLI shim: delegate to apply_for_feature."""
    from mage.orchestration.cosmetic_apply import apply_for_feature

    project_dir: Path = getattr(args, "project_dir", Path.cwd())
    model = getattr(args, "model", None)
    return await apply_for_feature(
        project_dir,
        args.feature_id,
        dry_run=getattr(args, "dry_run", False),
        model=model,
    )


async def cmd_cosmetic_list(args) -> int:
    """List cosmetic queue entries for a feature. Text or JSON output."""
    from mage.artifacts.cosmetic_state import load_state
    from mage.artifacts.mapping import MappingArtifact
    from mage.cosmetic_filters import FilterParseError, parse_filters

    project_dir: Path = getattr(args, "project_dir", Path.cwd())
    mapping_path = project_dir / "mapping.yaml"
    if not mapping_path.exists():
        print(
            f"mage cosmetic list: no mapping found at {mapping_path}",
            file=sys.stderr,
        )
        return 1
    mapping = MappingArtifact.load(mapping_path)
    state = load_state(project_dir)
    raw_filter = getattr(args, "filter", None)
    try:
        filters = parse_filters(raw_filter, subcommand="cosmetic list")
    except FilterParseError as e:
        print(f"mage cosmetic list: {e.message}", file=sys.stderr)
        return 2
    queue = [
        q for q in mapping.cosmetic_findings if q.get("feature_id") == args.feature_id
    ]
    if "sub_bid" in filters:
        allowed = filters["sub_bid"]
        available = {q["sub_bid"] for q in queue}
        missing = allowed - available
        if missing:
            print(
                f"mage cosmetic list: unknown sub_bid "
                f"{min(missing)!r} for feature {args.feature_id!r}",
                file=sys.stderr,
            )
            return 2
        queue = [q for q in queue if q["sub_bid"] in allowed]
    queue.sort(key=lambda q: q.get("sub_bid", ""))
    rows: list[dict] = []
    for q in queue:
        sub_bid = q.get("sub_bid", "")
        applied_record = state.applied.get(sub_bid)
        applied_at_value = getattr(applied_record, "applied_at", None)
        rows.append(
            {
                "feature_id": args.feature_id,
                "status": "applied" if applied_record is not None else "pending",
                "sub_bid": sub_bid,
                "scenario": q.get("scenario_name", ""),
                "file": q.get("location") or None,
                "applied_at": (
                    applied_at_value.isoformat()
                    if applied_at_value is not None
                    else None
                ),
            }
        )
    if getattr(args, "format", "text") == "json":
        print(json.dumps({"entries": rows}))
        return 0
    print(
        f"{'feature_id':<12}  {'status':<8}  "
        f"{'sub_bid':<18}  {'scenario':<18}  {'file':<24}  applied_at"
    )
    for row in rows:
        file_disp = row["file"] or "—"
        applied_at_disp = row["applied_at"] or "—"
        print(
            f"{row['feature_id']:<12}  {row['status']:<8}  "
            f"{row['sub_bid']:<18}  {row['scenario']:<18}  "
            f"{file_disp:<24}  {applied_at_disp}"
        )
    return 0


async def cmd_mapping_save(args) -> int:
    """Re-save mapping.yaml and emit MAPPING_SAVED.

    Used by E2E tests and external hooks that want to trigger the
    cosmetic watcher without modifying the mapping content.
    """
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = getattr(args, "project_dir", Path.cwd())
    log = EventsLog(project_dir / "events.jsonl")
    mapping = MappingArtifact.load(project_dir / "mapping.yaml")
    await mapping.save(project_dir / "mapping.yaml", events_log=log)
    return 0


async def cmd_cosmetic_watch(args) -> int:
    """Long-running daemon: auto-apply cosmetic queue items on MAPPING_SAVED."""
    from mage.orchestration.cosmetic_watcher import MappingArtifactWatcher

    project_dir: Path = getattr(args, "project_dir", Path.cwd())
    poll_interval_ms: int = getattr(args, "poll_interval_ms", 250)
    watcher = MappingArtifactWatcher(
        project_dir,
        poll_interval_ms=poll_interval_ms,
    )

    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        watcher.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            # Windows or non-main thread: skip signal handlers.
            pass

    await watcher.run()
    return 0


async def cmd_cosmetic_unwatch(args) -> int:
    """Stop the cosmetic watcher daemon by PID file, with SIGTERM/SIGKILL escalation."""
    from datetime import UTC, datetime

    from mage.orchestration.cosmetic_watcher import (
        _events_log_for,
        _request_remote_stop,
    )
    from mage.orchestration.events import Event, EventType

    project_dir: Path = getattr(args, "project_dir", Path.cwd())
    path = pid_file_path(project_dir)
    pid = read_pid(project_dir)
    if pid is None:
        print(
            f"mage cosmetic unwatch: no watcher running for {project_dir}",
            file=sys.stderr,
        )
        return 0
    if not is_alive(pid):
        remove_pid(project_dir)
        print(
            f"mage cosmetic unwatch: removed stale pid file for pid={pid}",
            file=sys.stderr,
        )
        events_log = _events_log_for(project_dir)
        await events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.COSMETIC_WATCHER_STALE_PID_REMOVED,
                payload={
                    "pid_file_path": str(path),
                    "recorded_pid": pid,
                },
            )
        )
        return 0
    await _request_remote_stop(
        project_dir=project_dir,
        target_pid=pid,
        requester_pid=os.getpid(),
        timeout_s=5.0,
        force=getattr(args, "force", False),
    )
    if read_pid(project_dir) is None:
        return 0
    print(
        "mage cosmetic unwatch: watcher did not stop after 5000ms; "
        "pass --force to escalate",
        file=sys.stderr,
    )
    return 3


def cmd_verify(args: argparse.Namespace) -> int:
    """Run mechanical verification on a single scenario."""
    project_dir: Path = args.project_dir
    mapping = (
        MappingArtifact.load(project_dir / "mapping.yaml")
        if (project_dir / "mapping.yaml").exists()
        else MappingArtifact(
            schema_version=2, project_id=project_dir.name, base_bids=[]
        )
    )
    # For Plan 1, we run with empty registries (host project can configure later).
    checks = default_check_set(registered_tags=set(), step_patterns=[])
    verifier = MechanicalVerifier(checks=checks)
    draft = ScenarioDraft(
        feature_path=args.feature,
        scenario_name=args.scenario,
        gherkin_text=args.feature.read_text(),
        tags=[],  # Tag parsing lives in Plan 3
        sub_bid=args.sub_bid,
        parent_base_bid=Base85BID(value=args.base_bid),
        step_texts=[],  # Step text extraction lives in Plan 3
    )
    results = verifier.verify(draft, mapping)
    failed = [r for r in results if r.outcome == "fail"]
    for r in results:
        status = "PASS" if r.outcome == "pass" else "FAIL"
        print(f"[{status}] {r.name}: {r.detail or ''}")
    return 0 if not failed else 1


async def _main(argv: list[str] | None = None) -> int:
    """CLI entry point (async). The `main` wrapper runs this on a fresh loop."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        raise SystemExit(0)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "plan" and args.plan_command == "show":
        return await cmd_plan_show(args)
    if args.command == "plan" and args.plan_command == "revise":
        return await cmd_plan_revise(args)
    if args.command == "run":
        return await cmd_run(args)
    if args.command == "review" and args.review_command == "show":
        return await cmd_review_show(args)
    if args.command == "inspect" and args.inspect_command == "show":
        return await cmd_inspect_show(args)
    if args.command == "settle" and args.settle_command == "run":
        return await cmd_settle_run(args)
    if args.command == "cosmetic" and args.cosmetic_command == "show":
        return await cmd_cosmetic_show(args)
    if args.command == "cosmetic" and args.cosmetic_command == "list":
        return await cmd_cosmetic_list(args)
    if args.command == "cosmetic" and args.cosmetic_command == "apply":
        return await cmd_cosmetic_apply(args)
    if args.command == "cosmetic" and args.cosmetic_command == "watch":
        return await cmd_cosmetic_watch(args)
    if args.command == "cosmetic" and args.cosmetic_command == "unwatch":
        return await cmd_cosmetic_unwatch(args)
    if args.command == "mapping" and args.mapping_command == "save":
        return await cmd_mapping_save(args)
    parser.print_help()
    raise SystemExit(1)


def main(*args) -> int:
    """Sync wrapper that runs the async CLI on a fresh event loop.

    Accepts the full argv as positional arguments (e.g. `main("--project-dir", "p", "verify", ...)`)
    or as a list (e.g. `main(["--project-dir", "p", "verify", ...])`) for backwards
    compatibility with the previous signature.
    """
    if len(args) == 1 and isinstance(args[0], list):
        argv = args[0]
    elif len(args) == 1 and args[0] is None or not args:
        argv = None
    else:
        argv = list(args)
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    sys.exit(main())
