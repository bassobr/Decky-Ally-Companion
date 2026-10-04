"""CPU boost: keep boost off and keep the frequency cap applied.

Ported from the CPU Boost Fix of Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT).

On the ROG Xbox Ally X (amd-pstate) every charger plug/unplug makes the firmware drop the
scaling_max_freq cap on all cores although boost is off. Re-writing scaling_max_freq on every
policy re-sends the cap. The slip can come back ~10 s after the event, so the cores are watched
for a while and kicked again when they go over the cap.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .. import sysfs
from ..log import logger
from ..module import Module, cancel_task

BOOST = "sys/devices/system/cpu/cpufreq/boost"
POLICY_GLOB = "sys/devices/system/cpu/cpu[0-9]*/cpufreq"
KICK_STEP_KHZ = 30_000
OVER_CAP_TOLERANCE_KHZ = 50_000
DEBOUNCE_S = 1.0
WATCH_WINDOW_S = 30.0
WATCH_POLL_S = 2.0
_CPU_RE = re.compile(r"/cpu(\d+)/cpufreq$")


def policies() -> List[str]:
    found = [(int(m.group(1)), p) for p in sysfs.sorted_glob(POLICY_GLOB) if (m := _CPU_RE.search(p))]
    return [p for _, p in sorted(found)]


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

    def set_options(self, opts: Dict[str, Any]) -> bool:
        if "refreshOnCharger" in opts:
            self.update_cfg({"refreshOnCharger": bool(opts["refreshOnCharger"])})
        return False

    def actions(self):
        return {"refresh_now": self.refresh_now}

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
        await self.kick_cap("apply")

    async def revert(self) -> None:
        self._stop_watch()
        sysfs.write_str(sysfs.p(BOOST), "1")
        # The re-sent cap is a frequency-QoS request that survives boost=1; lift it explicitly.
        lifted = 0
        for pol in policies():
            hw_max = sysfs.read_int(os.path.join(pol, "cpuinfo_max_freq"))
            if hw_max is not None and sysfs.try_write(os.path.join(pol, "scaling_max_freq"), str(hw_max), "[cpu_boost]"):
                lifted += 1
        logger.info("[cpu_boost] boost enabled, cap lifted on %d policies", lifted)

    def details(self) -> Dict[str, Any]:
        return {"boost": sysfs.read_str(sysfs.p(BOOST)), "refreshOnCharger": bool(self.cfg.get("refreshOnCharger", True)),
                "overCapCores": self.over_cap_count(), "policies": len(policies()), "kicks": self._kicks,
                "lastKick": self._last_kick,
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
        if not self.enabled:
            raise RuntimeError("CPU boost off is not enabled")
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
        if not self.enabled or not self.cfg.get("refreshOnCharger", True):
            return
        if event.get("ACTION") != "change" or event.get("POWER_SUPPLY_TYPE") != "Mains":
            return
        self.schedule_refresh("charger")

    def schedule_refresh(self, reason: str) -> None:
        loop = asyncio.get_event_loop()
        self._watch_until = loop.time() + WATCH_WINDOW_S
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = loop.create_task(self._watch(reason))
        else:
            self._kick_requested = True  # every event gets its own kick

    def _stop_watch(self) -> None:
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()
        self._watch_task = None

    async def _watch(self, reason: str) -> None:
        loop = asyncio.get_event_loop()
        await asyncio.sleep(DEBOUNCE_S)
        self._kick_requested = False
        await self.kick_cap(reason)
        await self.notify()
        while loop.time() < self._watch_until:
            await asyncio.sleep(WATCH_POLL_S)
            if not self.enabled:
                return
            if self._kick_requested:
                self._kick_requested = False
                await self.kick_cap(f"{reason}:event")
            elif self._cap_slipped():
                await self.kick_cap(f"{reason}:recheck")
                self._watch_until = loop.time() + WATCH_WINDOW_S  # the firmware is still settling
        await self.notify()
