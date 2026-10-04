"""Diagnostics report for the System page and bug reports."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from . import device, paths
from .util import read_json, run


def plugin_version() -> str:
    v = os.environ.get("DECKY_PLUGIN_VERSION")
    if v:
        return v
    pkg = read_json(os.path.join(paths.PLUGIN_DIR, "package.json"), {}) or {}
    return str(pkg.get("version", "dev"))


def user_session() -> Dict[str, Any]:
    """Proves the root/user boundary: who the dropped child is and whether its session bus answers."""
    who = run(["id", "-un"], timeout=5, as_user=True)
    sysd = run(["systemctl", "--user", "is-system-running"], timeout=10, as_user=True)
    return {"user": who.out.strip() if who.ok else f"rc={who.rc} {who.err.strip()[:80]}",
            "systemdUser": (sysd.out or sysd.err).strip()[:80]}


def collect(modules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "plugin": {"version": plugin_version(), "dir": paths.PLUGIN_DIR, "euid": os.geteuid()},
        "device": device.info(),
        "stack": device.stack(),
        "userSession": user_session(),
        "modules": modules or {},
    }


def render_text(d: Dict[str, Any]) -> str:
    return "Ally Companion diagnostics\n" + json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False)
