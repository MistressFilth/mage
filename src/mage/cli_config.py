"""`mage config` subcommand group."""

from __future__ import annotations

import sys

from pydantic import SecretStr

from mage import settings


def cmd_config_path() -> int:
    """Print the resolved config file path."""
    print(settings.config_file())
    return 0


def cmd_config_init() -> int:
    """Initialize the config file with built-in defaults."""
    try:
        path = settings.initialize_config()
    except settings.MageConfigAlreadyExists as exc:
        print(f"configuration already exists at {exc.path}", file=sys.stderr)
        return 2
    except settings.MageConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(path)
    return 0


def cmd_config_show() -> int:
    """Print the effective settings as TOML."""
    try:
        loaded = settings.load_settings()
    except settings.MageConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    out_lines: list[str] = []
    for field_name in loaded.__class__.model_fields:
        value = getattr(loaded, field_name)
        if isinstance(value, SecretStr):
            rendered = "***"
        else:
            rendered = _toml_basic_string(value)
        out_lines.append(f"{field_name} = {rendered}")
    print("\n".join(out_lines))
    return 0


def _toml_basic_string(value: object) -> str:
    """Render a Python value as a TOML basic-string literal.

    Booleans, integers, and floats are emitted unquoted; everything
    else falls through to :func:`json.dumps` for the same
    ``ensure_ascii=False`` round-trip semantics as
    :func:`mage.settings.serialize_config`.
    """
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if value is None:
        return '""'
    return json.dumps(str(value), ensure_ascii=False)
