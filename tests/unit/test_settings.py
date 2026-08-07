"""Settings substrate: schema, sources, load boundary, init."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from mage.settings import (
    MageConfigAlreadyExists,
    MageConfigurationError,
    MageSettings,
    config_file,
    initialize_config,
    load_settings,
    serialize_config,
)


@pytest.fixture(autouse=True)
def isolated_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAGE_XDG_CONFIG_HOME", str(tmp_path))


class TestSchema:
    def test_defaults(self) -> None:
        s = MageSettings()
        assert s.host_model_api_key is None
        assert s.log_level == "info"

    def test_log_level_accepts_each_literal(self) -> None:
        for level in ("debug", "info", "warning", "error"):
            assert MageSettings(log_level=level).log_level == level

    def test_log_level_rejects_unknown_literal(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MageSettings(log_level="verbose")

    def test_extra_keys_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MageSettings(unknown_field="x")  # type: ignore[call-arg]

    def test_host_model_api_key_uses_secretstr(self) -> None:
        s = MageSettings(host_model_api_key="secret-token")
        assert isinstance(s.host_model_api_key, SecretStr)
        assert s.host_model_api_key.get_secret_value() == "secret-token"


class TestPrecedence:
    def test_explicit_kwarg_wins_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAGE_LOG_LEVEL", "debug")
        s = load_settings(log_level="error")
        assert s.log_level == "error"

    def test_env_wins_over_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGE_LOG_LEVEL", "warning")
        s = load_settings()
        assert s.log_level == "warning"

    def test_explicit_none_does_not_mask_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAGE_LOG_LEVEL", "debug")
        s = load_settings(log_level=None)
        assert s.log_level == "debug"


class TestTomlSource:
    def test_toml_value_loads(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config = tmp_path / "mage" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('log_level = "warning"\n')
        s = load_settings()
        assert s.log_level == "warning"

    def test_env_overrides_toml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config = tmp_path / "mage" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('log_level = "warning"\n')
        monkeypatch.setenv("MAGE_LOG_LEVEL", "error")
        s = load_settings()
        assert s.log_level == "error"

    def test_malformed_toml_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config = tmp_path / "mage" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("this is = not valid toml [")
        with pytest.raises(MageConfigurationError) as exc_info:
            load_settings()
        assert exc_info.value.path == config
        assert "invalid" in str(exc_info.value)

    def test_unknown_toml_key_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config = tmp_path / "mage" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('unknown_field = "x"\n')
        with pytest.raises(MageConfigurationError):
            load_settings()


class TestInitializeConfig:
    def test_creates_file(self) -> None:
        path = initialize_config()
        assert path.exists()
        body = path.read_text()
        assert 'log_level = "info"' in body

    def test_refuses_overwrite(self) -> None:
        initialize_config()
        with pytest.raises(MageConfigAlreadyExists) as exc_info:
            initialize_config()
        assert exc_info.value.path == config_file()

    def test_round_trip(self) -> None:
        initialize_config()
        s = load_settings()
        assert s.log_level == "info"

    def test_atomic_publish(self, mocker: pytest.Mocker) -> None:
        """No half-written file is observable."""
        # Spy on os.link to confirm it's used.
        spy = mocker.spy(__import__("os"), "link")
        initialize_config()
        assert spy.called

    def test_filesystem_failure_raises_could_not_write(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Point XDG_CONFIG_HOME at a path we cannot mkdir into.
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            monkeypatch.setenv("MAGE_XDG_CONFIG_HOME", str(readonly / "subdir"))
            with pytest.raises(MageConfigurationError) as exc_info:
                initialize_config()
            assert exc_info.value.path == config_file()
            assert "could not write" in str(exc_info.value)
        finally:
            readonly.chmod(0o700)


class TestSerializeConfig:
    def test_basic_string_round_trip(self) -> None:
        body = serialize_config("info")
        assert body == 'log_level = "info"\n'

    def test_preserves_unicode(self) -> None:
        body = serialize_config("info-🪄")
        assert "🪄" in body
        assert "\\u" not in body  # ensure_ascii=False
