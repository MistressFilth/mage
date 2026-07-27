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
    show_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    # mage plan revise
    revise_parser = plan_subparsers.add_parser("revise", help="Record a Plan revision after halt")
    revise_parser.add_argument("--reason", type=str, required=True)
    revise_parser.add_argument("--approver", type=str, required=True)
    revise_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    # mage run
    run_parser = subparsers.add_parser("run", help="Run the pipeline")
    run_parser.add_argument("--from", dest="from_stage", type=str, default=None)
    run_parser.add_argument("--project-dir", type=Path, default=Path.cwd())

    return parser


def cmd_plan_show(args):
    """Display Plan + digest + last event."""
    from mage.artifacts.plan import PlanArtifact
    from mage.orchestration.events import EventsLog

    project_dir: Path = args.project_dir
    log = EventsLog(project_dir / "events.jsonl")
    plan_path = project_dir / "plan.md"

    print(f"Plan: {plan_path}")

    if not plan_path.exists():
        print("(Plan file does not exist on disk)")
        return

    # Find latest FINALIZED/REVISED event
    events = log.read_all()
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

    if halted_ctx is not None:
        print(f"Resuming pipeline from halted state (stage={halted_ctx.current_stage})")
        ctx = halted_ctx
    else:
        print(f"No halted state found at {state_dir}; nothing to resume.")
        return 0

    # Note: actual stage list construction deferred to Plan 6 (full pipeline wiring).
    # For Plan 2, this command verifies the resume mechanism works.
    print(f"Pipeline context loaded: project_dir={ctx.project_dir}")
    print("Note: full pipeline wiring (stage list construction) is Plan 6 work.")
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
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
