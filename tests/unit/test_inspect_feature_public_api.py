"""`InspectFeatureStage` public API contract (Plan 17).

The class exposes exactly one async, non-underscore-prefixed coroutine:
``run_pass``. Any future addition of a `run`-shaped method by virtue of
inheriting ``StageNode`` is forbidden by this test.
"""

from __future__ import annotations

import inspect

from mage.orchestration.inspect_feature import InspectFeatureStage


def test_run_pass_is_the_only_public_async_method():
    """`run_pass` is the sole public async entry on `InspectFeatureStage`."""
    public_async = [
        name
        for name, member in inspect.getmembers(InspectFeatureStage, predicate=inspect.iscoroutinefunction)
        if not name.startswith("_")
    ]
    assert public_async == ["run_pass"], (
        f"Unexpected public async surface: {public_async}; "
        "only `run_pass` should be exposed."
    )
