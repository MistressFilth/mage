"""CLI entry point for HAILERIS v2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import MappingArtifact
from mage.verification.host_overrides import default_check_set, load_host_config
from mage.verification.mechanical import (
    MechanicalVerifier,
    ScenarioDraft,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="mage",
        description="HAILERIS v2: spec-driven development pipeline",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # mage verify — run mechanical checks against a feature/scenario.
    verify = subparsers.add_parser("verify", help="Run mechanical verification on a scenario")
    verify.add_argument("--feature", type=Path, required=True, help="Path to the .feature file")
    verify.add_argument("--scenario", required=True, help="Scenario name within the feature")
    verify.add_argument("--sub-bid", required=True, help="Sub-BID for the scenario")
    verify.add_argument("--base-bid", required=True, help="Parent base-BID")

    # mage plan <subcommand>
    plan_parser = subparsers.add_parser("plan", help="Plan operations")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)

    # mage plan show
    show_parser = plan_subparsers.add_parser("show", help="Display Plan + digest")

    # mage plan revise
    revise_parser = plan_subparsers.add_parser("revise", help="Record a Plan revision after halt")
    revise_parser.add_argument("--reason", type=str, required=True)
    revise_parser.add_argument("--approver", type=str, required=True)

    # mage run
    run_parser = subparsers.add_parser("run", help="Run the pipeline")
    run_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    # mage review <subcommand>
    review_parser = subparsers.add_parser("review", help="Review operations")
    review_subparsers = review_parser.add_subparsers(dest="review_command", required=True)
    review_subparsers.add_parser("show", help="Display latest aggregate verdict")

    # mage review resume
    resume_parser = review_subparsers.add_parser("resume", help="Resume after review halt")
    resume_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    # mage inspect <subcommand>
    inspect_parser = subparsers.add_parser("inspect", help="Inspect operations")
    inspect_subparsers = inspect_parser.add_subparsers(dest="inspect_command", required=True)

    # mage inspect show
    inspect_show_parser = inspect_subparsers.add_parser(
        "show", help="Display latest Inspect artifact"
    )
    inspect_show_parser.add_argument("feature_id")
    inspect_show_parser.add_argument("--project-dir", type=Path, default=argparse.SUPPRESS)

    # mage settle <subcommand>
    settle_parser = subparsers.add_parser("settle", help="Settle operations")
    settle_subparsers = settle_parser.add_subparsers(dest="settle_command", required=True)

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

    return parser


def cmd_plan_show(args):
    """Display Plan + digest + last event."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    plan_path = project_dir / "plan.md"
    log = EventsLog(project_dir / "events.jsonl") if (project_dir / "events.jsonl").exists() else None

    print(f"Plan: {plan_path}")

    if not plan_path.exists():
        print("(Plan file does not exist on disk)")
        return

    # Find latest FINALIZED/REVISED event
    events = log.read_all() if log is not None else []
    plan_events = [
        e for e in events
        if e.event_type.value in ("plan_finalized", "plan_revised")
        and e.payload.get("plan_path") == str(plan_path)
    ]
    if not plan_events:
        print("(No PLAN_FINALIZED event — Plan is unfinalized)")
        return

    latest = max(plan_events, key=lambda e: e.timestamp)
    digest = latest.payload.get("plan_sha256") or latest.payload.get("new_sha256")
    print(f"Digest: {digest}")
    print(f"Last event: {latest.event_type.value.upper().replace('_', ' ')} at {latest.timestamp.isoformat()}")
    print()

    try:
        content = PlanArtifact.load(plan_path, log)
    except Exception as e:
        print(f"(Failed to load Plan: {e})")
        return

    lines = content.splitlines()
    preview = "\n".join(lines[:50])
    print(preview)
    if len(lines) > 50:
        print(f"\n... ({len(lines) - 50} more lines)")


def cmd_plan_revise(args):
    """Record a Plan revision after halt."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    plan_path = project_dir / "plan.md"

    if not plan_path.exists():
        print(f"mage plan revise: error: plan.md not found at {plan_path}", file=sys.stderr)
        sys.exit(2)

    # Check that a prior finalization exists
    events = log.read_all()
    plan_events = [
        e for e in events
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
        print("mage plan revise: warning: Plan digest unchanged; recording anyway", file=sys.stderr)

    new_digest = PlanArtifact.revise(
        plan_path,
        plan_path.read_text(encoding="utf-8"),
        reason=args.reason,
        human_approver=args.approver,
        events_log=log,
    )

    print(f"Plan revision recorded. New digest: {new_digest}")
    print("Restart the pipeline with: mage run")


def cmd_run(args):
    """Run the pipeline with halt handling and resume support."""
    from mage.orchestration.events import EventsLog
    from mage.orchestration.nodes import PipelineContext
    from mage.orchestration.persistence import FileStatePersistence

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    state_dir = project_dir / ".haileris" / "state"

    # Try to load halted context
    persistence = FileStatePersistence(
        state_dir=state_dir, state_type=PipelineContext
    )
    halted_ctx = persistence.load_state()

    raise NotImplementedError("mage run pipeline execution is deferred to Plan 6; stage wiring is not implemented")


def cmd_review_show(args):
    """Display the latest aggregate verdict for the project."""
    from mage.orchestration.events import EventsLog
    from mage.artifacts.verdict import VerdictArtifact

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")

    events = log.read_all()
    aggregate_events = [
        e for e in events if e.event_type.value == "review_aggregate_recorded"
    ]
    if not aggregate_events:
        print(f"mage review show: no aggregate verdicts found in {project_dir}", file=sys.stderr)
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
            aggregate = VerdictArtifact.load(aggregate_path, log)
            decision = aggregate.decision
        except Exception as e:
            print(
                f"mage review show: warning: failed to read aggregate at "
                f"{aggregate_path}: {e}",
                file=sys.stderr,
            )

    print(f"Latest aggregate verdict:")
    print(f"  Path:       {aggregate_path_str}")
    print(f"  Digest:     {digest}")
    print(f"  Decision:   {decision}")
    print(f"  Recorded:   {latest.timestamp.isoformat()}")


def cmd_inspect_show(args):
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

    content = InspectArtifact.load(latest, log)
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


def cmd_review_resume(args):
    """Verify a review halt and print resume readiness."""
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    events = log.read_all()
    halt_events = [e for e in events if e.event_type.value == "review_halt_persisted"]
    if not halt_events:
        print(f"mage review resume: error: no REVIEW_HALT_PERSISTED event found in {project_dir}", file=sys.stderr)
        sys.exit(2)

    print(f"Review halt found. Pipeline resume is ready (full wiring deferred to Plan 6).")
    print(f"Run: mage run --project-dir {project_dir}")


def cmd_settle_run(args):
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
            schema_version=1,
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
        stage.run_settle(ctx, feature_id=args.feature_id, disposition=disposition)
    except SettleError as error:
        print(f"mage settle run: error: {error}", file=sys.stderr)
        return 1
    print(f"Settle complete for {args.feature_id}: {disposition}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Run mechanical verification on a single scenario."""
    project_dir: Path = args.project_dir
    config = load_host_config(project_dir)
    mapping = MappingArtifact.load(project_dir / "mapping.yaml") if (project_dir / "mapping.yaml").exists() else MappingArtifact(
        schema_version=1, project_id=project_dir.name, base_bids=[]
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


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        raise SystemExit(0)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "plan" and args.plan_command == "show":
        cmd_plan_show(args)
        return 0
    if args.command == "plan" and args.plan_command == "revise":
        cmd_plan_revise(args)
        return 0
    if args.command == "run":
        return cmd_run(args)
    if args.command == "review" and args.review_command == "show":
        cmd_review_show(args)
        return 0
    if args.command == "inspect" and args.inspect_command == "show":
        return cmd_inspect_show(args)
    if args.command == "review" and args.review_command == "resume":
        cmd_review_resume(args)
        return 0
    if args.command == "settle" and args.settle_command == "run":
        return cmd_settle_run(args)
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
