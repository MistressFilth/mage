"""Static guard: enforce the mage run --feature-id plumbing (Plan 22).

Catches regression if anyone removes the CLI flag, the helper, or any of
the downstream wiring (PipelineContext.feature_id, FeatureRunner.feature_id).
Mirrors the Plan 13 / Plan 17 / Plan 19 static-guard pattern.

The previous revision used regex/grep across whole files, which is too
loose: a `feature_id: str = ""` declared anywhere (or `--feature-id`
appearing in any later sibling parser block) would satisfy the guards.
This rewrite scopes each assertion to the exact construct it cares about
by walking the parsed AST.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
MAGE = SRC / "mage"
CLI = MAGE / "cli.py"
NODES = MAGE / "orchestration" / "nodes.py"
RUNNER = MAGE / "orchestration" / "runner.py"


def _find_top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return the top-level FunctionDef with the given name, else raise."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Top-level function {name!r} not found in module")


def _find_top_level_class(tree: ast.Module, name: str) -> ast.ClassDef:
    """Return the top-level ClassDef with the given name, else raise."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Top-level class {name!r} not found in module")


def _run_parser_block_source(cli_tree: ast.Module) -> str:
    """Return the unparsed source of the `run_parser` block in build_parser().

    Scopes the check to the run_parser block alone: the assignment
    `run_parser = subparsers.add_parser(...)` plus all subsequent
    statements that call methods on `run_parser` (the chained
    `add_argument` calls). The next sibling parser assignment, any
    statement that does not target `run_parser`, or the end of the
    function terminates the block. AST comments are not present so they
    do not affect scoping.
    """
    build = _find_top_level_function(cli_tree, "build_parser")
    body = build.body
    start = None
    for idx, stmt in enumerate(body):
        if not isinstance(stmt, ast.Assign):
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "run_parser"):
            continue
        value = stmt.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "add_parser"
        ):
            continue
        start = idx
        break
    assert start is not None, (
        "Could not locate `run_parser = subparsers.add_parser(...)` in "
        "build_parser(); the static guard cannot enforce --feature-id."
    )
    end = len(body)
    for idx in range(start + 1, len(body)):
        stmt = body[idx]
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "run_parser"
            ):
                continue
        end = idx
        break
    block_nodes = body[start:end]
    return ast.unparse(ast.Module(body=block_nodes, type_ignores=[]))


def _pipeline_context_has_feature_id_field(nodes_tree: ast.Module) -> bool:
    """Return True if PipelineContext has a `feature_id: str = ""` field."""
    cls = _find_top_level_class(nodes_tree, "PipelineContext")
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        target = node.target
        ann = node.annotation
        value = node.value
        if (
            isinstance(target, ast.Name)
            and target.id == "feature_id"
            and isinstance(ann, ast.Name)
            and ann.id == "str"
            and isinstance(value, ast.Constant)
            and value.value == ""
        ):
            return True
    return False


def _feature_runner_init_has_feature_id_kwarg(runner_tree: ast.Module) -> bool:
    """Return True if FeatureRunner.__init__ declares `feature_id: str = ""`."""
    cls = _find_top_level_class(runner_tree, "FeatureRunner")
    for node in cls.body:
        if not (isinstance(node, ast.FunctionDef) and node.name == "__init__"):
            continue
        all_args = list(node.args.args) + list(node.args.kwonlyargs)
        for arg in all_args:
            if arg.arg != "feature_id":
                continue
            ann = arg.annotation
            if isinstance(ann, ast.Name) and ann.id == "str":
                return True
    return False


class TestCliFlagPresent:
    def test_run_parser_has_feature_id_argument(self):
        """The CLI parser must define --feature-id on the run subcommand."""
        tree = ast.parse(CLI.read_text())
        block = _run_parser_block_source(tree)
        assert "--feature-id" in block, (
            "run_parser must define --feature-id. If the feature is being "
            "deprecated, delete this test rather than the flag."
        )


class TestResolveHelperPresent:
    def test_resolve_feature_id_helper_defined(self):
        """The _resolve_feature_id helper must exist in src/mage/cli.py."""
        tree = ast.parse(CLI.read_text())
        try:
            _find_top_level_function(tree, "_resolve_feature_id")
        except AssertionError as exc:
            raise AssertionError(
                "_resolve_feature_id helper missing from src/mage/cli.py; "
                "Plan 22 tag-only resolution requires it."
            ) from exc


class TestPipelineContextField:
    def test_pipeline_context_feature_id_field_present(self):
        """PipelineContext.feature_id must remain (regression net for Plan 12)."""
        tree = ast.parse(NODES.read_text())
        assert _pipeline_context_has_feature_id_field(tree), (
            "PipelineContext.feature_id is missing or no longer defaults "
            "to ''; revert the regression."
        )


class TestFeatureRunnerConstructor:
    def test_feature_runner_accepts_feature_id(self):
        """FeatureRunner.__init__ must accept feature_id kwarg."""
        tree = ast.parse(RUNNER.read_text())
        assert _feature_runner_init_has_feature_id_kwarg(tree), (
            "FeatureRunner.__init__ no longer accepts feature_id kwarg; "
            "Plan 22 threading depends on this."
        )
