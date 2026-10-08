"""Settings persistence and preset resolution.

Two files in the audio directory, each with one writer: settings.json (profiles, per-game presets,
extras) is written by the backend, setup.json (the setup state) by the worker process. A lock
cannot span the two processes; one writer per file needs none. Both files belong to the user, so
everything read back is checked like input.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from typing import Any, Dict, Optional

from . import paths
from .constants import DEFAULT_PROFILE, DEFAULT_VOICING, PREGAIN_MAX_DB, PREGAIN_MIN_DB, PROFILE_IDS, VOICINGS
from .util import read_json, write_json

DEFAULTS: Dict[str, Any] = {
    "schema": 1,
    "enabled": True,
    "global": {"profile": DEFAULT_PROFILE, "voicing": DEFAULT_VOICING},
    "perApp": {},
    "extras": {"autogain": True, "dialog": True, "regulator": True, "virtualBass": False, "preGainDb": 0.0},
    "setup": {"done": False, "xmlSha256": None, "packageVersion": None, "converterVersion": None,
              "completedAt": None, "extrasSignature": None, "targetSink": None},
}
RECONVERT_KEYS = ("autogain", "dialog", "regulator", "virtualBass")
APP_ID = re.compile(r"^\d{1,20}$")

_lock = threading.Lock()  # within one process; the two files have one writer each


def _merge(defaults: Any, data: Any) -> Any:
    """Defaults filled in where `data` lacks a key or has the wrong type; unknown keys are kept."""
    if isinstance(defaults, dict):
        out = {}
        data = data if isinstance(data, dict) else {}
        for k, v in defaults.items():
            out[k] = _merge(v, data.get(k)) if k in data else json.loads(json.dumps(v))
        for k, v in data.items():
            if k not in out:
                out[k] = v
        return out
    if data is None:
        return json.loads(json.dumps(defaults))
    if isinstance(defaults, bool):
        return data if isinstance(data, bool) else defaults
    if isinstance(defaults, float):
        ok = isinstance(data, (int, float)) and not isinstance(data, bool) and math.isfinite(data)
        return float(data) if ok else defaults
    return data


def valid_profile(p: Any) -> bool:
    return isinstance(p, str) and p in PROFILE_IDS


def valid_voicing(v: Any) -> bool:
    return isinstance(v, str) and v in VOICINGS


def clamp_pregain(db: Any) -> float:
    try:
        v = float(db)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(PREGAIN_MIN_DB, min(PREGAIN_MAX_DB, v))


def _str_or_none(v: Any, limit: int = 200) -> Optional[str]:
    return v[:limit] if isinstance(v, str) else None


def clean_entry(entry: Any) -> Optional[Dict[str, Any]]:
    """A per-game preset; None when it is not one."""
    if not isinstance(entry, dict) or not valid_profile(entry.get("profile")) or not valid_voicing(entry.get("voicing")):
        return None
    name = entry.get("name")
    return {"profile": entry["profile"], "voicing": entry["voicing"], "enabled": bool(entry.get("enabled", True)),
            "name": name[:80] if isinstance(name, str) else ""}


def normalize(s: Dict[str, Any]) -> Dict[str, Any]:
    """`s` (already merged with DEFAULTS) with every value checked; changes and returns `s`."""
    g = s["global"]
    s["global"] = {"profile": g["profile"] if valid_profile(g.get("profile")) else DEFAULT_PROFILE,
                   "voicing": g["voicing"] if valid_voicing(g.get("voicing")) else DEFAULT_VOICING}
    per = s.get("perApp")
    s["perApp"] = {k: e for k, e in ((k, clean_entry(v)) for k, v in (per.items() if isinstance(per, dict) else []))
                   if isinstance(k, str) and APP_ID.match(k) and e}
    x = s["extras"]
    s["extras"] = {**{k: bool(x.get(k, DEFAULTS["extras"][k])) for k in RECONVERT_KEYS},
                   "preGainDb": clamp_pregain(x.get("preGainDb", 0.0))}
    st = s["setup"]
    s["setup"] = {"done": bool(st.get("done")), **{k: _str_or_none(st.get(k)) for k in DEFAULTS["setup"] if k != "done"}}
    return s


def load() -> Dict[str, Any]:
    data = read_json(paths.SETTINGS_FILE, {})
    s = _merge(DEFAULTS, data if isinstance(data, dict) else {})
    setup = read_json(paths.SETUP_FILE)
    if isinstance(setup, dict):
        s["setup"] = _merge(DEFAULTS["setup"], setup)
    return normalize(s)


def save(s: Dict[str, Any]) -> None:
    """The backend's part. The setup state lives in setup.json; until migrate_setup has moved it,
    the copy in settings.json stays."""
    out = {k: v for k, v in normalize(_merge(DEFAULTS, s)).items() if k != "setup"}
    if not os.path.exists(paths.SETUP_FILE) and isinstance(s.get("setup"), dict):
        out["setup"] = s["setup"]
    with _lock:
        write_json(paths.SETTINGS_FILE, out)


def update_section(section: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """The worker's part: merge `values` into the setup state on disk; returns all settings."""
    if section != "setup":
        raise ValueError("only the setup section is written this way")
    with _lock:
        s = load()
        s["setup"].update(values)
        s = normalize(s)
        write_json(paths.SETUP_FILE, s["setup"])
        return s


def migrate_setup() -> bool:
    """Ally Companion 0.4 kept the setup state in settings.json: copy it to setup.json once."""
    if os.path.exists(paths.SETUP_FILE):
        return False
    data = read_json(paths.SETTINGS_FILE)
    if not isinstance(data, dict) or not isinstance(data.get("setup"), dict):
        return False
    write_json(paths.SETUP_FILE, normalize(_merge(DEFAULTS, {"setup": data["setup"]}))["setup"])
    return True


def extras_signature(extras: Dict[str, Any]) -> str:
    sig = {k: bool(extras.get(k, DEFAULTS["extras"][k])) for k in RECONVERT_KEYS}
    return hashlib.sha1(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:12]


def presets_stale(s: Dict[str, Any]) -> bool:
    """The presets were converted with other extras (changed since, or a conversion did not finish)."""
    return extras_signature(s["extras"]) != s["setup"].get("extrasSignature")


def resolve(s: Dict[str, Any], app_id: Optional[str]) -> Dict[str, Any]:
    if app_id:
        entry = (s.get("perApp") or {}).get(str(app_id))
        if entry and entry.get("enabled", True) and valid_profile(entry.get("profile")) and valid_voicing(entry.get("voicing")):
            return {"profile": entry["profile"], "voicing": entry["voicing"], "source": "app", "appId": str(app_id)}
    g = s.get("global") or {}
    profile = g.get("profile") if valid_profile(g.get("profile")) else DEFAULT_PROFILE
    voicing = g.get("voicing") if valid_voicing(g.get("voicing")) else DEFAULT_VOICING
    return {"profile": profile, "voicing": voicing, "source": "global", "appId": str(app_id) if app_id else None}
