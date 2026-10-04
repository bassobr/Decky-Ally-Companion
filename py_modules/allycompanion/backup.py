"""Backups of all settings as JSON files in ~/Documents/Ally Companion, readable and restorable."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List

from . import paths, userfs
from .constants import PLUGIN_NAME

# per-module state that is not a setting and must not travel between installations
TRANSIENT = {"news": ("items", "fetchedAt", "lastAttempt", "error", "channel", "notified"),
             "battery": ("fullOnce", "history"),
             "profiles": ("perfBaseline",)}
NAME = re.compile(r"^ally-companion-\d{8}-\d{6}\.json$")


def backup_dir() -> str:
    return os.path.join(paths.HOME, "Documents", PLUGIN_NAME)


def build(modules: Dict[str, Any], audio: Dict[str, Any], version: str) -> Dict[str, Any]:
    clean = {mid: {k: v for k, v in sec.items() if k not in TRANSIENT.get(mid, ())} for mid, sec in modules.items()}
    return {"plugin": PLUGIN_NAME, "version": version, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "modules": clean, "audio": audio}


def write(data: Dict[str, Any]) -> str:
    name = f"ally-companion-{time.strftime('%Y%m%d-%H%M%S')}.json"
    userfs.write(os.path.join(backup_dir(), name), (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(), 0o644)
    return name


def listing() -> List[Dict[str, Any]]:
    try:
        names = sorted((n for n in os.listdir(backup_dir()) if NAME.match(n)), reverse=True)
    except OSError:
        return []
    return [{"name": n, "size": os.path.getsize(os.path.join(backup_dir(), n))} for n in names]


def read(name: str) -> Dict[str, Any]:
    if not NAME.match(name or ""):
        raise ValueError("not a backup file name")
    with open(os.path.join(backup_dir(), name), "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("plugin") != PLUGIN_NAME or not isinstance(data.get("modules"), dict):
        raise ValueError("not an Ally Companion backup")
    return data
