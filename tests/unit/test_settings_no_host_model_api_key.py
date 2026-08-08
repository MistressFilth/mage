"""Pin removal of MageSettings.host_model_api_key (P31 task 7)."""

from __future__ import annotations

import inspect


class TestMageSettingsShape:
    def test_host_model_api_key_field_gone(self) -> None:
        from mage.settings import MageSettings

        assert "host_model_api_key" not in MageSettings.model_fields

    def test_load_settings_signature(self) -> None:
        from mage.settings import load_settings

        sig = inspect.signature(load_settings)
        assert "host_model_api_key" not in sig.parameters

    def test_load_settings_no_key_returns_instance(
        self, monkeypatch, tmp_path
    ) -> None:
        from mage.settings import load_settings

        # Point XDG_CONFIG_HOME at a clean tmp dir so this test never
        # reads a leftover config file from the user environment.
        monkeypatch.setenv("MAGE_XDG_CONFIG_HOME", str(tmp_path))
        s = load_settings()
        assert s is not None


class TestMageEnvSettingsSource:
    def test_does_not_read_host_model_api_key(self, monkeypatch) -> None:
        from mage.settings import MageEnvSettingsSource, MageSettings

        monkeypatch.setenv("MAGE_HOST_MODEL_API_KEY", "leaked")
        src = MageEnvSettingsSource(MageSettings)
        values = src()
        assert "host_model_api_key" not in values
