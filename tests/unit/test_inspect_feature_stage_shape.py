"""Class-shape assertions for `InspectFeatureStage` after Plan 17.

`InspectFeatureStage` is a feature-level service, not a graph stage.
These tests pin that contract so a future refactor cannot silently
reintroduce `StageNode` or the `_run` placeholder.
"""

from __future__ import annotations

from mage.orchestration.inspect_feature import InspectFeatureStage
from mage.orchestration.nodes import StageNode


def test_inspect_feature_stage_is_not_a_stage_node_subclass():
    """`InspectFeatureStage` is not a graph stage."""
    assert not issubclass(InspectFeatureStage, StageNode)


def test_inspect_feature_stage_has_no__run_method():
    """No `_run` method should be defined on the class."""
    assert "_run" not in InspectFeatureStage.__dict__, (
        "_run should be removed from InspectFeatureStage; "
        f"found attrs starting with '_run': "
        f"{[k for k in InspectFeatureStage.__dict__ if k.startswith('_run')]}"
    )
