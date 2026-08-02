"""Pin the default values of the Plan 6 follow-up journal-window fields."""

from __future__ import annotations

from mage.verification.host_overrides import HostConfig


class TestDefaultWindowSizes:
    """Spec R21: defaults match the pre-PR module constants exactly."""

    def test_per_scenario_window_default_is_5(self):
        assert HostConfig().per_scenario_window == 5

    def test_cross_scenario_window_default_is_3(self):
        assert HostConfig().cross_scenario_window == 3
