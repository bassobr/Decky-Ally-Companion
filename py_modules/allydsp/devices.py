"""Supported devices: display name, ASUS API query and pinned fallback package per codec subsystem id.
The registry lives in defaults/fallback-sources.json; keys are lowercase SSIDs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import paths
from .util import read_json

DEFAULT_CDN = "https://dlcdnets.asus.com"
SOURCE_KEYS = ("asus_api", "package")


def normalize_ssid(ssid: Any) -> str:
    return str(ssid or "").strip().lower()


def load_registry(path: Optional[str] = None) -> Dict[str, Any]:
    """Return {"asus_cdn": ..., "devices": {ssid: {"name", "asus_api", "package"}}}.

    A legacy file with top-level asus_api/package and no per-device values applies
    those to every listed device."""
    raw = read_json(path or paths.FALLBACK_SOURCES, {}) or {}
    legacy = {k: raw.get(k) for k in SOURCE_KEYS if raw.get(k)}
    devices: Dict[str, Dict[str, Any]] = {}
    for key, entry in (raw.get("devices") or {}).items():
        ssid = normalize_ssid(key)
        if not ssid or not isinstance(entry, dict):
            continue
        dev = dict(legacy)
        dev.update({k: v for k, v in entry.items() if not k.startswith("_")})
        dev["ssid"] = ssid
        dev.setdefault("name", ssid)
        dev["package"] = dict(dev.get("package") or {})
        devices[ssid] = dev
    return {"asus_cdn": raw.get("asus_cdn") or DEFAULT_CDN, "devices": devices}


def registry() -> Dict[str, Dict[str, Any]]:
    return load_registry()["devices"]


def lookup(ssid: Any) -> Optional[Dict[str, Any]]:
    return registry().get(normalize_ssid(ssid))


def supported_ssids() -> List[str]:
    return sorted(registry())


def display_name(ssid: Any) -> Optional[str]:
    dev = lookup(ssid)
    return dev.get("name") if dev else None
