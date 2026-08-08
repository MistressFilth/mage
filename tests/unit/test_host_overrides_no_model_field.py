"""Pin removal of HostConfig.model field (P31 task 8)."""

from __future__ import annotations


class TestHostConfigShape:
    def test_model_field_gone(self):
        from mage.verification.host_overrides import HostConfig
        assert "model" not in HostConfig.model_fields

    def test_default_construction_no_model_attr(self):
        from mage.verification.host_overrides import HostConfig
        cfg = HostConfig()
        assert not hasattr(cfg, "model") or "model" not in cfg.model_fields
