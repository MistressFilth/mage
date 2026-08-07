"""mage's directory layout, composed from resolved roots.

Every application directory is defined here and nowhere else. This is
the module the rest of the codebase imports; :mod:`mage.xdg` is an
implementation detail behind it.

The layout, by role:

=========================  ============================================
User config                ``<config_root>/mage/``
User data                  ``<data_root>/mage/``
Cache                      ``<cache_root>/mage/``
State                      ``<state_root>/mage/``
Runtime                    ``<runtime_root>/mage/``
=========================  ============================================

Only Linux gives each role its own root. macOS folds config and state
into the data directory; Windows folds all four into ``%LOCALAPPDATA%``.
Where they coincide, sibling directories end up sharing a parent.
"""

from __future__ import annotations

import os
from pathlib import Path

from mage import xdg

APP = "mage"

__all__ = [
    "APP",
    "app_cache_dir",
    "app_config_dir",
    "app_data_dir",
    "app_runtime_dir",
    "app_state_dir",
]


def app_data_dir() -> Path:
    """``<data_root>/mage``. Not created."""
    return xdg.data_home() / APP


def app_config_dir() -> Path:
    """``<config_root>/mage``. Not created."""
    return xdg.config_home() / APP


def app_cache_dir() -> Path:
    """``<cache_root>/mage``. Not created."""
    return xdg.cache_home() / APP


def app_state_dir() -> Path:
    """``<state_root>/mage``. Not created."""
    return xdg.state_home() / APP


def app_runtime_dir() -> Path:
    """``<runtime_root>/mage``, created.

    If the advertised runtime root cannot be used, fall back to
    ``<state_root>/mage/run``. Environments routinely export
    ``XDG_RUNTIME_DIR`` without creating it — WSL, containers, cron,
    and ssh sessions with no login session all do — and the
    specification sanctions a replacement directory rather than a hard
    failure.

    Mode ``0700`` is applied on POSIX, where the specification asks for
    it, and is re-applied on every call so a loosened directory heals
    itself. It is skipped on Windows: ``os.chmod`` there honors only
    the read-only bit, so calling it would imply a guarantee that does
    not hold.
    """
    path = xdg.runtime_dir() / APP
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = xdg.state_home() / APP / "run"
        path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path
