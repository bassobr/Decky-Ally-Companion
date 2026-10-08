"""CPU boost: keep boost off and keep the frequency cap applied.

Ported from the CPU Boost Fix of Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT).

On the ROG Xbox Ally X (amd-pstate) every charger plug/unplug makes the firmware drop the
scaling_max_freq cap on all cores although boost is off. Re-writing scaling_max_freq on every
policy re-sends the cap. The slip can come back ~10 s after the event, so the cores are watched
for a while and kicked again when they go over the cap.

On the ROG Ally X (Z1 Extreme) the cap survives charger events (measured with four loaded cores:
cap, CPPC max_perf and core clocks unchanged across unplug and replug), so there the module only
keeps boost off; the cap refresh is not offered.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .. import device, sysfs
from ..log import logger
from ..module import Module, cancel_task

BOOST = "sys/devices/system/cpu/cpufreq/boost"
POLICY_GLOB = "sys/devices/system/cpu/cpu[0-9]*/cpufreq"
COOLING_GLOB = "sys/class/thermal/cooling_device*"
KICK_STEP_KHZ = 30_000
OVER_CAP_TOLERANCE_KHZ = 50_000
DEBOUNCE_S = 1.0
WATCH_WINDOW_S = 30.0
WATCH_POLL_S = 2.0
_CPU_RE = re.compile(r"/cpu(\d+)/cpufreq$")


def policies() -> List[str]:
    found = [(int(m.group(1)), p) for p in sysfs.sorted_glob(POLICY_GLOB) if (m := _CPU_RE.search(p))]
    return [p for _, p in sorted(found)]


def refresh_processor_cooling() -> int:
    """Have the ACPI processor cooling devices recompute their frequency limit; returns how many.

    The kernel keeps that limit as a share of cpuinfo_max_freq taken when the cooling state was last
    set, and boost does not update it. Set while boost was off, it holds every core at the base clock
    once boost is back on (RC73XA, Linux 7.2: 2.0 instead of 5.1 GHz). Writing the current state
    again recomputes it; the throttling level stays the same."""
    done = 0
    for d in sysfs.sorted_glob(COOLING_GLOB):
        if sysfs.read_str(os.path.join(d, "type")) != "Processor":
            continue
        state = sysfs.read_str(os.path.join(d, "cur_state"))
        if state is not None and sysfs.try_write(os.path.join(d, "cur_state"), state, "[cpu_boost]"):
            done += 1
    return done


class CpuBoost(Module):
    id = "cpu_boost"
    title = "CPU boost off"
    toggle = True
    defaults = {"enabled": False, "refreshOnCharger": True}

    def __init__(self) -> None:
        super().__init__()
        self._watch_task: Optional[asyncio.Task] = None
        self._watch_until = 0.0
        self._kick_requested = False
        self._kicks = 0
        self._last_kick = ""
        self._override: Optional[bool] = None  # game profile: True = keep boost off, False = boost on

    @property
    def active(self) -> bool:
        """Whether boost is kept off right now: the setting, unless a game profile says otherwise."""
        return self.enabled if self._override is None else self._override

    async def reapply_if_enabled(self, force: bool = False) -> None:
        if not self.active or not self.supported()[0]:
            return
        try:
            await self.apply()
            self.last_error = ""
        except Exception as e:  # noqa: BLE001
            logger.exception("[cpu_boost] apply failed")
            self.last_error = str(e)

    async def set_enabled(self, on: bool) -> None:
        """The switch on the page; a running game's profile still decides while it runs."""
        self.update_cfg({"enabled": bool(on)})
        self.last_error = ""
        try:
            await (self.apply() if self.active else self.revert())
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] %s failed", self.id, "apply" if self.active else "revert")
            self.last_error = str(e)

    async def set_override(self, values: Optional[Dict[str, Any]]) -> None:
        """Game profile {"boost": bool}; None goes back to the setting."""
        new = None if not isinstance(values, dict) or "boost" not in values else not bool(values["boost"])
        if new == self._override:
            return
        before = self.active
        self._override = new
        if self.active:
            await self.reapply_if_enabled()
        elif before:
            await self.revert()

    def set_options(self, opts: Dict[str, Any]) -> bool:
        if "refreshOnCharger" in opts:
            self.update_cfg({"refreshOnCharger": bool(opts["refreshOnCharger"])})
        return False

    def actions(self):
        return {"refresh_now": self.refresh_now}

    @staticmethod
    def cap_slips() -> bool:
        """Whether the firmware may drop the cap on charger events (unknown boards: assume so)."""
        return not device.cap_holds_on_charger()

    def supported(self) -> Tuple[bool, str]:
        if not os.path.exists(sysfs.p(BOOST)):
            return False, "cpufreq boost control not available"
        if "asus" not in sysfs.dmi("sys_vendor").lower():
            return False, "only for ASUS devices"
        return True, ""

    def is_applied(self) -> bool:
        return sysfs.read_str(sysfs.p(BOOST)) == "0"

    async def apply(self) -> None:
        sysfs.write_str(sysfs.p(BOOST), "0")
        logger.info("[cpu_boost] boost disabled")
        if self.cap_slips():
            await self.kick_cap("apply")

    async def revert(self) -> None:
        # A kick in flight puts the old cap back when it ends: let it end before the cap is lifted.
        await cancel_task(self._watch_task)
        self._watch_task = None
        async with self._lock:
            sysfs.write_str(sysfs.p(BOOST), "1")
            # The re-sent cap is a frequency-QoS request that survives boost=1; lift it explicitly.
            lifted = 0
            for pol in policies():
                hw_max = sysfs.read_int(os.path.join(pol, "cpuinfo_max_freq"))
                if hw_max is not None and sysfs.try_write(os.path.join(pol, "scaling_max_freq"), str(hw_max), "[cpu_boost]"):
                    lifted += 1
            cooling = refresh_processor_cooling()
        logger.info("[cpu_boost] boost enabled, cap lifted on %d policies, %d processor cooling limits refreshed",
                    lifted, cooling)

    def details(self) -> Dict[str, Any]:
        return {"boost": sysfs.read_str(sysfs.p(BOOST)), "capSlips": self.cap_slips(),
                "refreshOnCharger": bool(self.cfg.get("refreshOnCharger", True)),
                "overCapCores": self.over_cap_count(), "policies": len(policies()), "kicks": self._kicks,
                "lastKick": self._last_kick, "override": self._override,
                "watching": self._watch_task is not None and not self._watch_task.done()}

    async def start(self) -> None:
        await self.reapply_if_enabled()
        if self.ctx and self.ctx.uevent:
            self.ctx.uevent.subscribe("power_supply", self._on_power_event)

    async def stop(self) -> None:
        if self.ctx and self.ctx.uevent:
            self.ctx.uevent.unsubscribe("power_supply", self._on_power_event)
        await cancel_task(self._watch_task)
        self._watch_task = None

    async def on_resume(self, slept_s: float) -> None:
        await self.reapply_if_enabled()

    async def refresh_now(self) -> None:
        if not self.active:
            raise RuntimeError("CPU boost off is not enabled")
        if not self.cap_slips():
            raise RuntimeError("Not needed on this device: the cap survives charger events")
        self.schedule_refresh("manual")

    # ------------------------------------------------------------- cap refresh
    def over_cap_count(self) -> int:
        n = 0
        for pol in policies():
            cur = sysfs.read_int(os.path.join(pol, "scaling_cur_freq"))
            mx = sysfs.read_int(os.path.join(pol, "scaling_max_freq"))
            if cur is not None and mx is not None and cur > mx + OVER_CAP_TOLERANCE_KHZ:
                n += 1
        return n

    def _cap_slipped(self) -> bool:
        return sysfs.read_str(sysfs.p(BOOST)) != "0" or self.over_cap_count() > 0

    async def kick_cap(self, reason: str) -> None:
        """Re-send scaling_max_freq on every policy."""
        async with self._lock:
            if sysfs.read_str(sysfs.p(BOOST)) != "0":
                sysfs.write_str(sysfs.p(BOOST), "0")
            saved = []
            try:
                for pol in policies():
                    path = os.path.join(pol, "scaling_max_freq")
                    mx = sysfs.read_int(path)
                    if mx is not None and sysfs.try_write(path, str(mx - KICK_STEP_KHZ), "[cpu_boost]"):
                        saved.append((path, mx))
                await asyncio.sleep(0.2)
            finally:
                for path, mx in saved:  # restore even when cancelled mid-kick
                    sysfs.try_write(path, str(mx), "[cpu_boost]")
            self._kicks += 1
            self._last_kick = reason
            logger.info("[cpu_boost] cap kicked on %d policies (%s)", len(saved), reason)

    async def _on_power_event(self, event: Dict[str, str]) -> None:
        if not self.active or not self.cap_slips() or not self.cfg.get("refreshOnCharger", True):
            return
        if event.get("ACTION") != "change" or event.get("POWER_SUPPLY_TYPE") != "Mains":
            return
        self.schedule_refresh("charger")

    def schedule_refresh(self, reason: str) -> None:
        loop = asyncio.get_running_loop()
        self._watch_until = loop.time() + WATCH_WINDOW_S
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = loop.create_task(self._watch(reason))
        else:
            self._kick_requested = True  # every event gets its own kick

    async def _watch(self, reason: str) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(DEBOUNCE_S)
        self._kick_requested = False
        await self.kick_cap(reason)
        await self.notify()
        while loop.time() < self._watch_until:
            await asyncio.sleep(WATCH_POLL_S)
            if not self.active:
                return
            if self._kick_requested:
                self._kick_requested = False
                await self.kick_cap(f"{reason}:event")
            elif self._cap_slipped():
                await self.kick_cap(f"{reason}:recheck")
                self._watch_until = loop.time() + WATCH_WINDOW_S  # the firmware is still settling
        await self.notify()
