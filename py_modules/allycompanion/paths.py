"""Filesystem layout; DECKY_* variables take precedence, the CLI falls back to the same locations."""
from __future__ import annotations

import os

from .constants import PLUGIN_NAME


def _plugin_dir_default() -> str:
    here = os.path.dirname(os.path.abspath(__file__))  # .../py_modules/allycompanion
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))


HOME = os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~")
USER = os.environ.get("DECKY_USER") or os.environ.get("SUDO_USER") or os.environ.get("USER") or "deck"
PLUGIN_DIR = os.environ.get("ALLYCOMPANION_PLUGIN_DIR") or os.environ.get("DECKY_PLUGIN_DIR") or _plugin_dir_default()
SETTINGS_DIR = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR") or os.path.join(HOME, "homebrew", "settings", PLUGIN_NAME)
RUNTIME_DIR = os.environ.get("DECKY_PLUGIN_RUNTIME_DIR") or os.path.join(HOME, "homebrew", "data", PLUGIN_NAME)
LOG_DIR = os.environ.get("DECKY_PLUGIN_LOG_DIR") or os.path.join(HOME, "homebrew", "logs", PLUGIN_NAME)

SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
PUBKEY_FILE = os.path.join(PLUGIN_DIR, "minisign.pub")

# Tests point this at a fake tree; every sysfs/procfs/os-release read goes through it.
SYSROOT = os.environ.get("ALLYCOMPANION_SYSROOT", "/")


def sys_path(*parts: str) -> str:
    return os.path.join(SYSROOT, *(p.lstrip("/") for p in parts))


def ensure_dirs() -> None:
    """Decky creates these as the user; a missing one is created as the user too, never by root."""
    from . import userfs

    for d in (SETTINGS_DIR, RUNTIME_DIR, LOG_DIR):
        if not os.path.isdir(d):
            userfs.mkdir(d)
