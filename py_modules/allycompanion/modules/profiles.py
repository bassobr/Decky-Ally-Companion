"""Game profiles: per-game lighting, vibration strength, performance profile, CPU boost and fan curve.

Each entry holds optional parts. When the game starts, the parts go to the matching modules as
overrides (lighting, vibration, cpu_boost, fan); when it ends, the overrides are cleared. The
performance profile is set through steamos-manager: Steam keeps a single global platform profile,
so the one active at game start is restored when the game ends. Per-game speaker presets stay
with the audio module (its perApp list), which the UI shows next to these.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from .. import dbus
from ..constants import STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH
from ..log import logger
from ..module import Module

# part name -> module that takes it as an override
OVERRIDES = {"lighting": "lighting", "vibration": "vibration", "cpuBoost": "cpu_boost", "fan": "fan"}
PARTS = (*OVERRIDES, "performance")
PERF_IFACE = f"{STEAMOS_MANAGER_BUS}.PerformanceProfile1"


def get_perf_profile() -> Optional[str]:
    v = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, PERF_IFACE, "PerformanceProfile", user_bus=True)
    return str(v) if v else None


def set_perf_profile(profile: str) -> None:
    dbus.set_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, PERF_IFACE, "PerformanceProfile", "s", profile, True)


class Profiles(Module):
    id = "profiles"
    title = "Game profiles"
    defaults = {"apps": {}, "perfBaseline": None}

    def __init__(self) -> None:
        super().__init__()
        self.running_app: Optional[str] = None
        self._perf_profiles: Optional[list] = None

    def actions(self):
        return {"set_app": self.set_app, "remove_app": self.remove_app}

    def apps(self) -> Dict[str, Any]:
        a = self.cfg.get("apps")
        return dict(a) if isinstance(a, dict) else {}

    def details(self) -> Dict[str, Any]:
        if not self._perf_profiles:  # steamos-manager may not be up yet: ask again next time
            v = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, PERF_IFACE,
                                      "AvailablePerformanceProfiles", user_bus=True)
            self._perf_profiles = [str(x) for x in v] if isinstance(v, list) else []
        return {"apps": self.apps(), "runningApp": self.running_app, "performanceProfiles": self._perf_profiles,
                "performanceProfile": get_perf_profile()}

    async def start(self) -> None:
        # a game's profile may still be active from before a restart of the plugin
        if self.cfg.get("perfBaseline"):
            await self._performance(None)

    async def on_app_changed(self, app_id: Optional[str]) -> None:
        self.running_app = app_id
        await self._push(self.apps().get(app_id) if app_id else None)

    async def _push(self, entry: Optional[Dict[str, Any]]) -> None:
        mods = self.ctx.modules if self.ctx else {}
        blocked = self.ctx.blocked if self.ctx else {}
        for part, mid in OVERRIDES.items():
            m = mods.get(mid)
            if m is None or mid in blocked or not m.supported()[0]:
                continue
            values = (entry or {}).get(part)
            try:
                await m.set_override(values if values else None)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                logger.exception("[profiles] %s override failed", part)
        try:
            await self._performance((entry or {}).get("performance"))
        except Exception:  # noqa: BLE001
            logger.exception("[profiles] performance profile failed")

    async def _performance(self, values: Optional[Dict[str, Any]]) -> None:
        """Set the game's platform profile, remembering the one to go back to."""
        wanted = (values or {}).get("profile")
        baseline = self.cfg.get("perfBaseline")
        if wanted:
            current = await asyncio.to_thread(get_perf_profile)
            if baseline is None:
                self.update_cfg({"perfBaseline": current})
            if current != wanted:
                await asyncio.to_thread(set_perf_profile, wanted)
                logger.info("[profiles] performance profile %s", wanted)
        elif baseline:
            await asyncio.to_thread(set_perf_profile, baseline)
            self.update_cfg({"perfBaseline": None})
            logger.info("[profiles] performance profile back to %s", baseline)

    async def set_app(self, appId: str, part: str, values: Optional[Dict[str, Any]] = None, name: str = "") -> None:  # noqa: N803
        """Set (values) or clear (None) one part of a game's profile."""
        if part not in PARTS:
            raise ValueError(f"unknown part {part!r}")
        apps = self.apps()
        entry = dict(apps.get(str(appId)) or {})
        if name:
            entry["name"] = str(name)[:80]
        if values:
            entry[part] = dict(values)
        else:
            entry.pop(part, None)
        if any(p in entry for p in PARTS):
            apps[str(appId)] = entry
        else:
            apps.pop(str(appId), None)
        self.update_cfg({"apps": apps})
        if str(appId) == self.running_app:
            await self._push(apps.get(str(appId)))

    async def remove_app(self, appId: str) -> None:  # noqa: N803
        apps = self.apps()
        apps.pop(str(appId), None)
        self.update_cfg({"apps": apps})
        if str(appId) == self.running_app:
            await self._push(None)

    async def uninstall(self) -> None:
        if self.cfg.get("perfBaseline"):
            await self._performance(None)
