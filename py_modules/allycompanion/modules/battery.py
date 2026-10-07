"""Battery and firmware power settings.

The charge limit goes through steamos-manager (BatteryChargeLimit1 on the session bus), the same
interface Steam's own setting uses, so both always agree. asus-armoury adds the MCU power saving
switch (with it on, the controller MCU loses its settings in sleep, which the vibration and
lighting modules re-send) and the POST boot sound.

"Charge to 100 % once" lifts the limit until the battery reports full, then puts it back. The
health history keeps one sample per day (full and design energy), read from sysfs once an hour.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import dbus, sysfs
from ..constants import STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH
from ..log import logger
from ..module import Module, cancel_task

BAT = "sys/class/power_supply/BAT0"
ARMOURY = "sys/class/firmware-attributes/asus-armoury/attributes"
CHARGE_IFACE = f"{STEAMOS_MANAGER_BUS}.BatteryChargeLimit1"
HISTORY_CHECK_S = 3600
HISTORY_MAX = 400
FULL_ONCE_POLL_S = 120
MIN_LIMIT = 10  # sanity bound for stored values
DEFAULT_MIN_LIMIT = 50  # when steamos-manager suggests none
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def armoury(name: str) -> Optional[str]:
    return sysfs.read_str(sysfs.p(f"{ARMOURY}/{name}/current_value"))


def set_armoury(name: str, value: str) -> None:
    path = sysfs.p(f"{ARMOURY}/{name}/current_value")
    if not os.path.exists(path):
        raise OSError(f"asus-armoury attribute {name} not available")
    sysfs.write_str(path, value)


def battery_info() -> Dict[str, Any]:
    def rd(name: str) -> Optional[int]:
        return sysfs.read_int(sysfs.p(f"{BAT}/{name}"))

    full, design = rd("energy_full"), rd("energy_full_design")
    cycles = rd("cycle_count")
    return {
        "capacity": rd("capacity"),
        "status": sysfs.read_str(sysfs.p(f"{BAT}/status")),
        "healthPct": round(100.0 * full / design, 1) if full and design else None,
        "energyFullWh": round(full / 1e6, 1) if full else None,
        "energyDesignWh": round(design / 1e6, 1) if design else None,
        "cycles": cycles if cycles else None,  # the firmware reports 0
        "powerW": round((rd("power_now") or 0) / 1e6, 1),
    }


def history_sample(info: Dict[str, Any], day: str) -> Optional[Dict[str, Any]]:
    if info.get("healthPct") is None:
        return None
    return {"d": day, "h": info["healthPct"], "e": info["energyFullWh"], "c": info.get("cycles")}


def _number(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def clean_history(history: Any) -> List[Dict[str, Any]]:
    """Samples as history_sample writes them; anything else is dropped."""
    out = []
    for s in history if isinstance(history, list) else []:
        if not isinstance(s, dict) or not isinstance(s.get("d"), str) or not _DAY.match(s["d"]) or _number(s.get("h")) is None:
            continue
        c = s.get("c")
        out.append({"d": s["d"], "h": _number(s["h"]), "e": _number(s.get("e")),
                    "c": c if isinstance(c, int) and not isinstance(c, bool) and c >= 0 else None})
    return out[-HISTORY_MAX:]


def add_sample(history: List[Dict[str, Any]], sample: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The history with today's sample appended, or None when today is already in it."""
    if sample is None or (history and history[-1].get("d") == sample["d"]):
        return None
    return (list(history) + [sample])[-HISTORY_MAX:]


class Battery(Module):
    id = "battery"
    title = "Battery"
    defaults: Dict[str, Any] = {"fullOnce": None, "history": []}

    def __init__(self) -> None:
        super().__init__()
        self._history_task: Optional[asyncio.Task] = None
        self._full_task: Optional[asyncio.Task] = None

    def normalize(self, cfg: Dict[str, Any]) -> None:
        full = cfg.get("fullOnce")
        ok = isinstance(full, int) and not isinstance(full, bool) and MIN_LIMIT <= full < 100
        cfg["fullOnce"] = full if ok else None
        cfg["history"] = clean_history(cfg.get("history"))

    def actions(self):
        return {"set_charge_limit": self.set_charge_limit, "set_mcu_powersave": self.set_mcu_powersave,
                "set_boot_sound": self.set_boot_sound, "charge_full_once": self.charge_full_once,
                "cancel_full_once": self.cancel_full_once}

    def supported(self) -> Tuple[bool, str]:
        if not os.path.isdir(sysfs.p(BAT)):
            return False, "no battery"
        return True, ""

    def details(self) -> Dict[str, Any]:
        limit = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, CHARGE_IFACE, "MaxChargeLevel", user_bus=True)
        minimum = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, CHARGE_IFACE,
                                        "SuggestedMinimumLimit", user_bus=True)
        mcu, sound = armoury("mcu_powersave"), armoury("boot_sound")
        return {
            **battery_info(),
            "chargeLimit": limit if isinstance(limit, int) and limit > 0 else None,
            "chargeLimitSupported": limit is not None,
            "chargeLimitMin": minimum if isinstance(minimum, int) else 50,
            "mcuPowersave": None if mcu is None else mcu == "1",
            "bootSound": None if sound is None else sound == "1",
            "pendingReboot": armoury("pending_reboot") == "1",
            "fullOnce": self.cfg.get("fullOnce") is not None,
            "history": self.cfg.get("history") or [],
        }

    async def start(self) -> None:
        self._history_task = asyncio.get_running_loop().create_task(self._history_loop())
        if self.cfg.get("fullOnce") is not None:
            self._watch_full()

    async def stop(self) -> None:
        await cancel_task(self._history_task)
        await cancel_task(self._full_task)

    async def _history_loop(self) -> None:
        while True:
            new = add_sample(self.cfg.get("history") or [],
                             history_sample(await asyncio.to_thread(battery_info), time.strftime("%Y-%m-%d")))
            if new is not None:
                self.update_cfg({"history": new})
            await asyncio.sleep(HISTORY_CHECK_S)

    @staticmethod
    def _read_limit() -> Optional[int]:
        v = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, CHARGE_IFACE, "MaxChargeLevel", user_bus=True)
        return v if isinstance(v, int) else None

    async def charge_full_once(self) -> None:
        if self.cfg.get("fullOnce") is not None:
            return
        limit = await asyncio.to_thread(self._read_limit)
        if not isinstance(limit, int) or limit <= 0:
            raise RuntimeError("no charge limit is set")
        await self._write_limit(None)
        self.update_cfg({"fullOnce": limit})  # only once the limit is really lifted
        logger.info("[battery] charging to 100 %% once, then back to %d %%", limit)
        self._watch_full()

    async def cancel_full_once(self) -> None:
        prev = self.cfg.get("fullOnce")
        await cancel_task(self._full_task)
        if prev is not None:
            await self._write_limit(int(prev))
            self.update_cfg({"fullOnce": None})

    def _watch_full(self) -> None:
        if self._full_task is None or self._full_task.done():
            self._full_task = asyncio.get_running_loop().create_task(self._full_loop())

    async def _full_loop(self) -> None:
        while self.cfg.get("fullOnce") is not None:
            if (await asyncio.to_thread(self._read_limit) or -1) > 0:
                # someone set a limit meanwhile (Steam's own setting): theirs stays
                self.update_cfg({"fullOnce": None})
                await self.notify()
                return
            info = await asyncio.to_thread(battery_info)
            if info.get("status") == "Full" or (info.get("capacity") or 0) >= 100:
                prev = int(self.cfg["fullOnce"])
                await self._write_limit(prev)
                self.update_cfg({"fullOnce": None})
                logger.info("[battery] full; charge limit back to %d %%", prev)
                await self.notify()
                return
            await asyncio.sleep(FULL_ONCE_POLL_S)

    async def set_charge_limit(self, level: Optional[int] = None) -> None:
        """The slider: a limit chosen by hand ends a running "charge to 100 % once"."""
        if self.cfg.get("fullOnce") is not None:
            await cancel_task(self._full_task)
            self.update_cfg({"fullOnce": None})
        await self._write_limit(level)

    @staticmethod
    def _min_limit() -> int:
        v = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, CHARGE_IFACE, "SuggestedMinimumLimit",
                                  user_bus=True)
        return v if isinstance(v, int) and 0 < v < 100 else DEFAULT_MIN_LIMIT

    async def _write_limit(self, level: Optional[int]) -> None:
        """level None or 100: no limit; never below steamos-manager's suggested minimum."""
        if level is None or int(level) >= 100:
            value = -1
        else:
            value = max(await asyncio.to_thread(self._min_limit), int(level))
        await asyncio.to_thread(dbus.set_property, STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, CHARGE_IFACE,
                                "MaxChargeLevel", "i", value, True)
        logger.info("[battery] charge limit %s", "off" if value < 0 else f"{value}%")

    async def set_mcu_powersave(self, on: bool) -> None:
        set_armoury("mcu_powersave", "1" if on else "0")
        logger.info("[battery] MCU power saving %s", "on" if on else "off")

    async def set_boot_sound(self, on: bool) -> None:
        set_armoury("boot_sound", "1" if on else "0")
