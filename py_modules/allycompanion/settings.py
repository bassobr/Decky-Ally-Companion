"""Settings persistence: one file, one section per module plus plugin-wide sections.

settings.json sits in a directory the user owns, so everything read from it is untrusted: values
take the type of their default (anything else falls back to the default) and each module checks
its own section further (Module.normalize).
"""
from __future__ import annotations

import json
import math
import threading
from typing import Any, Dict

from . import paths, safefs

DEFAULTS: Dict[str, Any] = {
    "schema": 1,
    "update": {"lastCheck": 0, "lastAttempt": 0, "latest": None, "error": None, "autoCheck": True},
    "migrated": [],
    "modules": {},
}

_lock = threading.Lock()


def _copy(v: Any) -> Any:
    return json.loads(json.dumps(v))


def _typed(default: Any, value: Any) -> Any:
    """`value` when it has the type of `default`; None defaults are free-form (the module checks)."""
    if default is None:
        return value
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return default
        if isinstance(default, int):
            return int(value) if float(value).is_integer() else default
        return float(value)
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(default, list):
        return value if isinstance(value, list) else _copy(default)
    return value


def merge(defaults: Any, data: Any) -> Any:
    """Defaults filled in where `data` lacks a key or has the wrong type; unknown keys are kept."""
    if isinstance(defaults, dict):
        data = data if isinstance(data, dict) else {}
        out = {k: merge(v, data[k]) if k in data else _copy(v) for k, v in defaults.items()}
        out.update({k: v for k, v in data.items() if k not in out and isinstance(k, str)})
        return out
    return _copy(defaults) if data is None else _typed(defaults, data)


def _normalize_update(u: Dict[str, Any]) -> None:
    latest = u.get("latest")
    if latest is not None:
        ok = isinstance(latest, dict) and isinstance(latest.get("version"), str) and isinstance(latest.get("assets"), dict)
        u["latest"] = {
            "tag": str(latest.get("tag") or ""), "version": latest["version"],
            "assets": {str(k): v for k, v in latest["assets"].items() if isinstance(v, str)},
            "html_url": latest.get("html_url") if isinstance(latest.get("html_url"), str) else None,
            "published_at": latest.get("published_at") if isinstance(latest.get("published_at"), str) else None,
            "prerelease": bool(latest.get("prerelease")),
        } if ok else None
    if u.get("error") is not None and not isinstance(u.get("error"), str):
        u["error"] = None


def load(module_defaults: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    defaults = _copy(DEFAULTS)
    defaults["modules"] = _copy(module_defaults)
    data = safefs.read_json(paths.SETTINGS_FILE, {})
    s = merge(defaults, data if isinstance(data, dict) else {})
    _normalize_update(s["update"])
    s["migrated"] = [x for x in s["migrated"] if isinstance(x, str)]
    return s


def save(s: Dict[str, Any]) -> None:
    data = (json.dumps(s, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    with _lock:
        safefs.write_bytes(paths.SETTINGS_FILE, data)
