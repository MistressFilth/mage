"""Static guard for Plan 28b — cosmetic_watcher run() try/finally scope.

The try: block in MappingArtifactWatcher.run() must sit ABOVE the
COSMETIC_WATCHER_STARTED event emit so the catch-up _handle_mapping_saved()
falls under the same finally: as the poll loop. This guard pins the
placement so a future refactor that moves the try: back below the STARTED
append (re-introducing the P26 finding) fails loudly.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "mage"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_method(
    tree: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    return None


def _find_first_try(method: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Try | None:
    """Return the first Try statement in the function body, or None."""
    for node in method.body:
        if isinstance(node, ast.Try):
            return node
    return None


def test_run_method_try_block_covers_started_emit() -> None:
    """The first try: statement in MappingArtifactWatcher.run() must wrap
    the await self.events_log.append(... COSMETIC_WATCHER_STARTED ...) call."""
    tree = _parse(SRC / "orchestration" / "cosmetic_watcher.py")
    cls = _find_class(tree, "MappingArtifactWatcher")
    assert cls is not None, "MappingArtifactWatcher class not found"
    method = _find_method(cls, "run")
    assert method is not None, "MappingArtifactWatcher.run() not found"

    first_try = _find_first_try(method)
    assert first_try is not None, "run() has no try: statement"

    # The first try: must be among the FIRST few statements in the function
    # body, AFTER the docstring and the log_path / parent.mkdir() setup
    # lines. P28b widened the try: scope to wrap both the STARTED emit
    # and the catch-up; the pre-P28b placement put the STARTED emit and
    # catch-up OUTSIDE the try:, which the unparse check below catches.
    # body[:4] = docstring + log_path + mkdir + try (current placement).
    assert first_try in method.body[:4], (
        "The try: must be among the first 4 statements in run() "
        "(docstring + log_path + parent.mkdir() + try); "
        f"current first statement is: {ast.dump(method.body[0])[:200]}"
    )

    # The COSMETIC_WATCHER_STARTED event emit must be inside the try: body.
    try_src = ast.unparse(first_try)
    assert "COSMETIC_WATCHER_STARTED" in try_src, (
        "The COSMETIC_WATCHER_STARTED event emit must be inside the try: block"
    )
    # And the finally: must emit COSMETIC_WATCHER_STOPPED.
    assert "COSMETIC_WATCHER_STOPPED" in try_src, (
        "The COSMETIC_WATCHER_STOPPED event emit must be in the finally: block"
    )
