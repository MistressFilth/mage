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

    return parser


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
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
