"""`mage config` subcommand group."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import TypedDict

from mage import settings
from mage.host_project_config import load_mage_toml

__all__ = ["cmd_config_init", "cmd_config_path", "cmd_config_show"]


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


def cmd_config_show(project_root: Path | None = None) -> int:
    """Print the effective settings as TOML.

    ``project_root`` defaults to the current working directory; it
    locates ``mage.toml`` for the ``[mage.toml]`` section. The XDG
    config file is parsed directly (not via
    :func:`mage.settings.load_settings`) because :class:`MageSettings`
    is strict about unknown keys and the providers table is the
    concern of :func:`mage.providers.config.load_xdg_providers`.
    """
    cfg_path = settings.config_file()
    try:
        data = _read_xdg_config(cfg_path)
    except settings.MageConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    out_lines: list[str] = [
        f"log_level = {json.dumps(data['log_level'], ensure_ascii=False)}"
    ]
    if data["default_provider"] is not None:
        out_lines.append(
            f"default_provider = {json.dumps(data['default_provider'], ensure_ascii=False)}"
        )

    if data["providers"]:
        out_lines.append("")
        out_lines.append("[providers]")
        for name in sorted(data["providers"]):
            raw = data["providers"][name]
            for key in ("base_url", "default_model", "api_key_env"):
                value = raw.get(key)
                if value is None:
                    continue
                out_lines.append(
                    f"  {name}.{key} = {json.dumps(str(value), ensure_ascii=False)}"
                )

    project_root_resolved = project_root if project_root is not None else Path.cwd()
    mage_toml_path = project_root_resolved / "mage.toml"
    out_lines.append("")
    out_lines.append("[mage.toml]")
    out_lines.append(f"  path = {json.dumps(str(mage_toml_path), ensure_ascii=False)}")
    if mage_toml_path.exists():
        cfg = load_mage_toml(project_root_resolved)
        if cfg.default_model is not None:
            out_lines.append(
                f"  default_model = {json.dumps(cfg.default_model, ensure_ascii=False)}"
            )
        for agent, model in sorted(cfg.agent_models.items()):
            out_lines.append(
                f"  agents.{agent} = {json.dumps(model, ensure_ascii=False)}"
            )

    print("\n".join(out_lines))
    return 0


class _XdgConfigView(TypedDict):
    log_level: str
    default_provider: str | None
    providers: dict[str, dict[str, object]]


def _read_xdg_config(cfg_path: Path) -> _XdgConfigView:
    """Parse the XDG config.toml into ``log_level`` / ``default_provider`` / ``providers``.

    Missing file returns built-in defaults (matches
    :func:`mage.providers.config.load_xdg_providers` semantics, where
    absent-file means "no providers registered"). Malformed TOML
    raises :class:`MageConfigurationError` so :func:`cmd_config_show`
    can print a diagnostic and exit 2 — same contract as the existing
    ``test_invalid_config_exits_2`` path.
    """
    if not cfg_path.exists():
        return {
            "log_level": settings.DEFAULT_LOG_LEVEL,
            "default_provider": None,
            "providers": {},
        }
    try:
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise settings.MageConfigurationError(cfg_path, str(exc)) from exc
    return {
        "log_level": data.get("log_level", settings.DEFAULT_LOG_LEVEL),
        "default_provider": data.get("default_provider"),
        "providers": data.get("providers", {}),
    }
