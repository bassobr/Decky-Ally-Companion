"""Battery and firmware power settings.

The charge limit goes through steamos-manager (BatteryChargeLimit1 on the session bus), the same
interface Steam's own setting uses, so both always agree. asus-armoury adds the MCU power saving
switch (with it on, the controller MCU loses its settings in sleep, which the vibration and
lighting modules re-send) and the POST boot sound.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional, Tuple

from .. import dbus, sysfs
from ..constants import STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH
from ..log import logger
from ..module import Module

BAT = "sys/class/power_supply/BAT0"
ARMOURY = "sys/class/firmware-attributes/asus-armoury/attributes"
CHARGE_IFACE = f"{STEAMOS_MANAGER_BUS}.BatteryChargeLimit1"


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


class Battery(Module):
    id = "battery"
    title = "Battery"
    defaults: Dict[str, Any] = {}

    def actions(self):
        return {"set_charge_limit": self.set_charge_limit, "set_mcu_powersave": self.set_mcu_powersave,
                "set_boot_sound": self.set_boot_sound}

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
        }

    async def set_charge_limit(self, level: Optional[int] = None) -> None:
        """level None or 100: no limit."""
        value = -1 if level is None or int(level) >= 100 else max(10, int(level))
        await asyncio.to_thread(dbus.set_property, STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH, CHARGE_IFACE,
                                "MaxChargeLevel", "i", value, True)
        logger.info("[battery] charge limit %s", "off" if value < 0 else f"{value}%")

    async def set_mcu_powersave(self, on: bool) -> None:
        set_armoury("mcu_powersave", "1" if on else "0")
        logger.info("[battery] MCU power saving %s", "on" if on else "off")

    async def set_boot_sound(self, on: bool) -> None:
        set_armoury("boot_sound", "1" if on else "0")
