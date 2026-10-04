"""Settings persistence: one file, one section per module plus plugin-wide sections."""
from __future__ import annotations

import json
import threading
from typing import Any, Dict

from . import paths
from .util import read_json, write_json

DEFAULTS: Dict[str, Any] = {
    "schema": 1,
    "update": {"lastCheck": 0, "lastAttempt": 0, "latest": None, "error": None, "autoCheck": True},
    "modules": {},
}

_lock = threading.Lock()


def _copy(v: Any) -> Any:
    return json.loads(json.dumps(v))


def merge(defaults: Any, data: Any) -> Any:
    """Defaults filled in where `data` lacks a key; unknown keys in `data` are kept."""
    if isinstance(defaults, dict):
        data = data if isinstance(data, dict) else {}
        out = {k: merge(v, data[k]) if k in data else _copy(v) for k, v in defaults.items()}
        out.update({k: v for k, v in data.items() if k not in out})
        return out
    return _copy(defaults) if data is None else data


def load(module_defaults: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    defaults = _copy(DEFAULTS)
    defaults["modules"] = _copy(module_defaults)
    return merge(defaults, read_json(paths.SETTINGS_FILE, {}) or {})


def save(s: Dict[str, Any]) -> None:
    with _lock:
        write_json(paths.SETTINGS_FILE, s)
