"""Other Decky plugins that drive the same hardware.

While one of them is installed and not disabled in Decky, the modules it covers stay passive (no
apply on start) and report the conflict; otherwise both plugins would fight over the same sysfs
attributes, files and HID commands.
"""
from __future__ import annotations

import os
from typing import Dict, List

from . import paths
from .util import read_json

COVERS: Dict[str, List[str]] = {
    "Ally Fix": ["vibration", "gyro", "gamepad_layout", "cpu_boost", "fan"],
    "Ally DSP": ["audio"],
    "HueSync": ["lighting"],
    "Ally Center": ["lighting", "cpu_boost", "fan"],
}


def plugins_dir() -> str:
    return os.path.join(paths.HOME, "homebrew", "plugins")


def active_plugins() -> List[str]:
    """Covering plugins that are installed and not disabled in Decky."""
    loader = read_json(os.path.join(paths.HOME, "homebrew", "settings", "loader.json"), {}) or {}
    disabled = set(loader.get("disabled_plugins") or [])
    return [name for name in COVERS
            if os.path.isfile(os.path.join(plugins_dir(), name, "plugin.json")) and name not in disabled]


def blocked() -> Dict[str, str]:
    """module id -> name of the plugin that blocks it."""
    out: Dict[str, str] = {}
    for name in active_plugins():
        for mid in COVERS[name]:
            out.setdefault(mid, name)
    return out
