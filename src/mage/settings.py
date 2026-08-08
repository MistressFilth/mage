"""Runtime configuration: env vars, XDG TOML, defaults.

Path resolution lives in :mod:`mage.paths`.

Configuration loads from three sources, in increasing priority:

1. **Defaults baked into the model** — :data:`DEFAULT_LOG_LEVEL`.
2. **The XDG config file** — ``$XDG_CONFIG_HOME/mage/config.toml``,
   applied by :class:`XdgTomlSettingsSource`.
3. **Environment variables** — ``MAGE_HOST_MODEL_API_KEY`` and
   ``MAGE_LOG_LEVEL``, applied by :class:`MageEnvSettingsSource`.
4. **Explicit arguments** to :func:`load_settings` — win over every
   source above; used by the CLI for overrides.

The schema is strict: unknown keys, wrong-typed values, empty or
relative paths, and malformed TOML all surface as
:class:`MageConfigurationError` carrying the offending file path so the
user can fix it.

The first-time configuration file is created by :func:`initialize_config`,
which writes the deterministic defaults via :func:`serialize_config` and
publishes them atomically with ``os.link`` so a half-written file can
never appear at :func:`config_file`.
"""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, field_validator
from pydantic.fields import FieldInfo
from pydantic_core import ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

from mage.paths import app_config_dir

__all__ = [
    "DEFAULT_LOG_LEVEL",
    "MageConfigAlreadyExists",
    "MageConfigurationError",
    "MageSettings",
    "config_file",
    "initialize_config",
    "load_settings",
    "serialize_config",
]

DEFAULT_LOG_LEVEL = "info"

LogLevel = Literal["debug", "info", "warning", "error"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class MageSettings(BaseSettings):
    """Top-level settings; ``extra=forbid`` and ordered custom sources."""

    model_config = SettingsConfigDict(extra="forbid")

    host_model_api_key: SecretStr | None = None
    log_level: LogLevel = DEFAULT_LOG_LEVEL

    @field_validator("log_level", mode="before")
    @classmethod
    def _validate_log_level(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            raise ValueError("log_level must not be empty or whitespace-only")
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order: init → env → toml. Later sources lose to earlier ones."""
        del env_settings, dotenv_settings, file_secret_settings
        return (
            init_settings,
            MageEnvSettingsSource(settings_cls),
            XdgTomlSettingsSource(settings_cls),
        )


# ---------------------------------------------------------------------------
# Custom sources
# ---------------------------------------------------------------------------


class MageEnvSettingsSource(PydanticBaseSettingsSource):
    """Flat ``MAGE_*`` environment variables."""

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        api_key = os.environ.get("MAGE_HOST_MODEL_API_KEY")
        if api_key is not None:
            values["host_model_api_key"] = api_key
        log_level = os.environ.get("MAGE_LOG_LEVEL")
        if log_level is not None:
            values["log_level"] = log_level
        return values


class XdgTomlSettingsSource(TomlConfigSettingsSource):
    """The single XDG config file at :func:`config_file`."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls, toml_file=config_file())


# ---------------------------------------------------------------------------
# Loading boundary
# ---------------------------------------------------------------------------


class MageConfigurationError(RuntimeError):
    """A config file failed validation. The offending path is on ``.path``.

    The default wording is "invalid" because the common case is a
    read-side validation failure (malformed TOML, unknown keys, wrong
    types). Other failure modes pass a ``kind`` that describes them
    accurately: ``kind="could not write"`` for write-side failures
    during :func:`initialize_config`, and ``kind="existing"`` for
    :class:`MageConfigAlreadyExists`. Neither a permission error nor an
    untouched pre-existing file is an invalid configuration file.
    """

    def __init__(self, path: Path, detail: str, *, kind: str = "invalid") -> None:
        self.path = path
        super().__init__(f"{kind} configuration at {path}: {detail}")


class MageConfigAlreadyExists(MageConfigurationError):
    """The configuration file already exists; initialization was refused.

    The pre-existing file is left exactly as it was —
    :func:`initialize_config` does not parse it. The user can move it
    aside, or call :func:`load_settings` to inspect it.

    Rendered with ``kind="existing"``: an untouched, unparsed file has
    not been judged invalid, and saying so would misdirect a library
    consumer reading the message. The CLI prints its own wording, so
    this text surfaces only to programmatic callers.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        MageConfigurationError.__init__(
            self, path, "refusing to overwrite", kind="existing"
        )


def config_file() -> Path:
    """``<XDG_CONFIG_HOME>/mage/config.toml``."""
    return app_config_dir() / "config.toml"


def load_settings(
    *,
    host_model_api_key: str | None = None,
    log_level: str | None = None,
) -> MageSettings:
    """Build :class:`MageSettings` honoring all four precedence layers.

    Explicit keyword arguments win over everything else; passing
    ``log_level=None`` does **not** mask an environment value the way
    an explicit ``log_level=""`` would — ``None`` means "leave this
    field to the next source down."
    """
    values: dict[str, Any] = {}
    if host_model_api_key is not None:
        values["host_model_api_key"] = host_model_api_key
    if log_level is not None:
        values["log_level"] = log_level
    try:
        return MageSettings(**values)
    except (SettingsError, ValidationError, tomllib.TOMLDecodeError, OSError) as exc:
        raise MageConfigurationError(config_file(), str(exc)) from exc


# ---------------------------------------------------------------------------
# First-time initialization
# ---------------------------------------------------------------------------


def serialize_config(log_level: str) -> str:
    """Render the configuration file body for ``log_level``.

    ``json.dumps(..., ensure_ascii=False)`` produces a TOML basic
    string literal that is also a valid JSON string literal — escapes
    for backslashes, control characters, and the delimiter
    double-quote, with the actual UTF-8 bytes preserved for non-ASCII
    content.
    """
    return f"log_level = {json.dumps(log_level, ensure_ascii=False)}\n"


def initialize_config() -> Path:
    """Create the XDG config file with built-in defaults.

    Refuses to overwrite an existing file: raises
    :class:`MageConfigAlreadyExists` and leaves the file untouched (it
    is not parsed). Publication is atomic via ``os.link`` so a reader
    either sees no file or the fully-written file — never a
    half-written one.
    """
    target = config_file()
    if target.exists():
        raise MageConfigAlreadyExists(target)
    # Probe writability on the highest existing ancestor before
    # attempting mkdir + mkstemp. On POSIX, ``chmod 0o500`` denies
    # write access and mkdir fails as expected. On Windows, the
    # same chmod sets only FILE_ATTRIBUTE_READONLY on the
    # directory, which mkdir / mkstemp silently ignore — a real
    # ACL probe via ``os.access(parent, os.W_OK)`` is what catches
    # the case there. Without the probe, the mkdir try/except below
    # would succeed and the test suite's "filesystem failure"
    # scenario would silently write into a directory the user
    # meant to lock.
    ancestor = target.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not os.access(ancestor, os.W_OK):
        raise MageConfigurationError(
            target,
            f"parent directory {ancestor} is not writable",
            kind="could not write",
        )
    fd = -1
    temporary: Path | None = None
    descriptor_open = False
    try:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
            )
        except OSError as exc:
            raise MageConfigurationError(
                target, str(exc), kind="could not write"
            ) from exc
        temporary = Path(temporary_name)
        descriptor_open = True
        payload = serialize_config(DEFAULT_LOG_LEVEL)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            descriptor_open = False
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise MageConfigAlreadyExists(target) from exc
        return target
    except MageConfigAlreadyExists:
        raise
    except OSError as exc:
        raise MageConfigurationError(target, str(exc), kind="could not write") from exc
    finally:
        if descriptor_open:
            os.close(fd)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
