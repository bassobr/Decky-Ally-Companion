"""One-time import of the settings of the plugins Ally Companion replaces.

Runs once per source plugin, after that plugin is gone (its settings directory stays behind when
Decky removes it). A module section is only filled when it still has its defaults.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from . import conflicts, paths
from .log import logger
from .util import read_json


def _settings_of(plugin: str) -> Dict[str, Any]:
    data = read_json(os.path.join(paths.HOME, "homebrew", "settings", plugin, "settings.json"), {})
    return data if isinstance(data, dict) else {}


def from_ally_fix(src: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    v = src.get("vibration") or {}
    if v:
        out["vibration"] = {k2: v[k1] for k1, k2 in (("enabled", "enabled"), ("left", "left"), ("right", "right"),
                            ("linked", "linked"), ("enhanced", "enhanced"), ("mirror_triggers", "mirror_triggers"))
                            if k1 in v}
    g = src.get("gyro") or {}
    if g:
        out["gyro"] = {k2: g[k1] for k1, k2 in (("enabled", "enabled"), ("mode", "mode"),
                       ("steam_cfg_prev", "steamCfgPrev")) if k1 in g}
    if "gamepad_layout" in src:
        out["gamepad_layout"] = {"enabled": bool((src["gamepad_layout"] or {}).get("enabled"))}
    c = src.get("cpu_boost") or {}
    if c:
        out["cpu_boost"] = {k2: c[k1] for k1, k2 in (("enabled", "enabled"), ("refresh_on_charger", "refreshOnCharger"))
                            if k1 in c}
    f = src.get("fan") or {}
    if f:
        out["fan"] = {k: f[k] for k in ("enabled", "curves") if k in f}
    return out


SOURCES: Dict[str, Callable[[Dict[str, Any]], Dict[str, Dict[str, Any]]]] = {
    "Ally Fix": from_ally_fix,
}


def register(name: str, convert: Callable[[Dict[str, Any]], Dict[str, Dict[str, Any]]]) -> None:
    SOURCES[name] = convert


def run(settings: Dict[str, Any], defaults: Dict[str, Dict[str, Any]]) -> List[str]:
    """Import what is due; returns the plugins imported now. Mutates `settings`."""
    done = settings.setdefault("migrated", [])
    active = set(conflicts.active_plugins())
    imported = []
    for name, convert in SOURCES.items():
        if name in done or name in active:
            continue
        src = _settings_of(name)
        if not src:
            continue
        for mid, values in convert(src).items():
            section = settings["modules"].get(mid)
            if section is None or section != defaults.get(mid):
                continue
            section.update(values)
        done.append(name)
        imported.append(name)
        logger.info("imported the settings of %s", name)
    return imported
