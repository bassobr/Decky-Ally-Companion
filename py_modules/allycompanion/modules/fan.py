"""Fans: pin the fan curve so the EC cannot get stuck at full speed, plus custom curves.

The pinning is ported from the Fan Noise Fix of Ally Fix (https://github.com/lonsdaleite/Ally-Fix,
MIT). Occasionally after resume both fans spin at maximum and never settle; writing the curve with
pwm*_enable=1 brings the EC back. asus-wmi resets pwm*_enable to 2 on every thermal-profile change
and never restores curves after resume, so a watchdog keeps the curve pinned.

For each thermal profile the module pins the curve that is there: the factory curve of that
profile (loaded through pwm_enable=3) or whatever another tool wrote while pinned. A custom curve
set in the UI replaces the remembered curve of the current profile.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

from .. import sysfs
from ..log import logger
from ..module import Module, cancel_task

TTP = "sys/devices/platform/asus-nb-wmi/throttle_thermal_policy"
PROFILE_NAMES = {0: "balanced", 1: "performance", 2: "low-power"}
POINTS = 8
FANS = ("pwm1", "pwm2")
RPM_FAILSAFE = 6000
FAILSAFE_MAX_TEMP_C = 65.0  # above this, >6000 rpm is legitimate load
WATCHDOG_PERIOD_S = 5.0
RESUME_SETTLE_S = 3.0
PWM_MAX = 255
TEMP_RANGE = (20, 110)

Curve = Dict[str, List[int]]  # {"temps": [...], "pwm1": [...], "pwm2": [...]}


def valid(curve: Optional[Curve]) -> bool:
    if not curve:
        return False
    try:
        return all(len(curve.get(k, [])) == POINTS and min(curve[k]) >= 0 for k in ("temps", *FANS))
    except (TypeError, ValueError):
        return False


def sanitize(curve: Any) -> Curve:
    """A curve from the UI: 8 points, temperatures and duty cycles non-decreasing and in range."""
    if not isinstance(curve, dict):
        raise ValueError("curve must be an object")
    out: Curve = {}
    for key, (lo, hi) in (("temps", TEMP_RANGE), ("pwm1", (0, PWM_MAX)), ("pwm2", (0, PWM_MAX))):
        vals = [max(lo, min(hi, int(v))) for v in list(curve.get(key, []))]
        if len(vals) != POINTS:
            raise ValueError(f"{key} needs {POINTS} points")
        for i in range(1, POINTS):
            vals[i] = max(vals[i], vals[i - 1])
        out[key] = vals
    return out


class Fan(Module):
    id = "fan"
    title = "Fan curve pinning"
    toggle = True
    defaults = {"enabled": False, "curves": {}}

    def __init__(self) -> None:
        super().__init__()
        self._task: Optional[asyncio.Task] = None
        self._last_event = ""
        self._override: Optional[Curve] = None  # game profile curve, pinned while the game runs

    @property
    def active(self) -> bool:
        return self.enabled or self._override is not None

    async def reapply_if_enabled(self, force: bool = False) -> None:
        if not self.active or not self.supported()[0]:
            return
        try:
            await self.apply()
            self.last_error = ""
        except Exception as e:  # noqa: BLE001
            logger.exception("[fan] apply failed")
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
        """Game profile {"curve": {...}}; None goes back to the pinned or firmware curve."""
        new = sanitize(values["curve"]) if values and values.get("curve") else None
        if new == self._override:
            return
        self._override = new
        if self.active:
            self._start_watchdog()
            async with self._lock:
                self._last_event = self._pin("game profile" if new else "game ended", force_write=True)
        else:
            await self.revert()

    def actions(self):
        return {"restore_factory": self.restore_factory, "set_curve": self.set_curve}

    # ------------------------------------------------------------- hwmon
    @staticmethod
    def curve_dir() -> Optional[str]:
        return sysfs.find_hwmon("asus_custom_fan_curve")

    @staticmethod
    def temp() -> Optional[float]:
        d = sysfs.find_hwmon("k10temp")
        v = sysfs.read_int(os.path.join(d, "temp1_input")) if d else None
        return v / 1000.0 if v is not None else None

    @staticmethod
    def rpm() -> Tuple[Optional[int], Optional[int]]:
        d = sysfs.find_hwmon("asus")
        if not d:
            return None, None
        return sysfs.read_int(os.path.join(d, "fan1_input")), sysfs.read_int(os.path.join(d, "fan2_input"))

    @staticmethod
    def profile() -> str:
        ttp = sysfs.read_int(sysfs.p(TTP))
        return PROFILE_NAMES.get(ttp, f"ttp{ttp}") if ttp is not None else "unknown"

    def enable_state(self) -> Tuple[Optional[int], Optional[int]]:
        d = self.curve_dir()
        if not d:
            return None, None
        return sysfs.read_int(os.path.join(d, "pwm1_enable")), sysfs.read_int(os.path.join(d, "pwm2_enable"))

    def _write_enable(self, value: int) -> None:
        d = self.curve_dir()
        if not d:
            raise OSError("asus_custom_fan_curve hwmon not found")
        for fan in FANS:
            sysfs.write_str(os.path.join(d, f"{fan}_enable"), str(value))

    def read_curve(self) -> Curve:
        d = self.curve_dir()
        if not d:
            raise OSError("asus_custom_fan_curve hwmon not found")
        curve: Curve = {"temps": [sysfs.read_int(os.path.join(d, f"pwm1_auto_point{i}_temp"), -1) for i in range(1, POINTS + 1)]}
        for fan in FANS:
            curve[fan] = [sysfs.read_int(os.path.join(d, f"{fan}_auto_point{i}_pwm"), -1) for i in range(1, POINTS + 1)]
        return curve

    def _write_curve(self, curve: Curve) -> None:
        d = self.curve_dir()
        if not d:
            raise OSError("asus_custom_fan_curve hwmon not found")
        for fan in FANS:
            for i in range(POINTS):
                sysfs.write_str(os.path.join(d, f"{fan}_auto_point{i + 1}_temp"), str(curve["temps"][i]))
                sysfs.write_str(os.path.join(d, f"{fan}_auto_point{i + 1}_pwm"), str(curve[fan][i]))

    # ------------------------------------------------------------- snapshots
    def snapshots(self) -> Dict[str, Curve]:
        c = self.cfg.get("curves")
        return dict(c) if isinstance(c, dict) else {}

    def _save_snapshot(self, profile: str, curve: Curve) -> None:
        curves = self.snapshots()
        curves[profile] = curve
        self.update_cfg({"curves": curves})

    def _pin(self, reason: str, force_write: bool = False) -> str:
        """Ensure the current profile's curve is loaded and enabled; returns what was done."""
        profile = self.profile()
        en1, en2 = self.enable_state()
        curve = self.read_curve()
        if self._override is not None:
            if force_write or en1 != 1 or en2 != 1 or curve != self._override:
                self._write_curve(self._override)
                self._write_enable(1)
                return f"pinned the game's curve ({reason})"
            return ""
        snap = self.snapshots().get(profile)
        if en1 == 1 and en2 == 1 and not force_write:
            if not valid(curve):
                return ""  # transient read failure: do not adopt garbage
            if valid(snap) and curve != snap:
                self._save_snapshot(profile, curve)
                return f"adopted external curve for {profile}"
            if not valid(snap):
                self._save_snapshot(profile, curve)
                return f"captured curve for {profile}"
            return ""
        if valid(snap):
            try:
                snap = sanitize(snap)
            except (TypeError, ValueError):
                snap = None
        if not valid(snap):
            self._write_enable(3)  # loads the factory curve of the current profile
            curve = self.read_curve()
            self._save_snapshot(profile, curve)
            action = f"captured factory curve for {profile}"
        else:
            curve = snap  # type: ignore[assignment]
            action = f"restored curve for {profile}"
        self._write_curve(curve)
        self._write_enable(1)
        return f"{action} ({reason})"

    def _failsafe_tripped(self) -> bool:
        t = self.temp()
        if t is not None and t >= FAILSAFE_MAX_TEMP_C:
            return False
        return any(r is not None and r > RPM_FAILSAFE for r in self.rpm())

    # ------------------------------------------------------------- module interface
    def supported(self) -> Tuple[bool, str]:
        if self.curve_dir() is None:
            return False, "asus_custom_fan_curve hwmon not found"
        if sysfs.read_int(sysfs.p(TTP)) is None:
            return False, "throttle_thermal_policy not available"
        return True, ""

    def is_applied(self) -> bool:
        return self.enable_state() == (1, 1)

    async def apply(self) -> None:
        self._start_watchdog()
        async with self._lock:
            done = self._pin("apply")
        self._last_event = done or "pinned"
        logger.info("[fan] %s", self._last_event)

    async def revert(self) -> None:
        self._stop_watchdog()
        async with self._lock:
            self._write_enable(2)
        self._last_event = "unpinned"
        logger.info("[fan] curve unpinned (firmware auto)")

    def details(self) -> Dict[str, Any]:
        profile = self.profile()
        cur: Optional[Curve] = None
        try:
            cur = self.read_curve()
        except OSError:
            pass
        return {"profile": profile, "pwmEnable": list(self.enable_state()), "rpm": list(self.rpm()), "temp": self.temp(),
                "curve": cur, "snapshotProfiles": sorted(self.snapshots()), "lastEvent": self._last_event,
                "override": self._override is not None}

    async def start(self) -> None:
        await self.reapply_if_enabled()

    async def stop(self) -> None:
        await cancel_task(self._task)
        self._task = None

    async def on_resume(self, slept_s: float) -> None:
        if not self.active:
            return
        await asyncio.sleep(RESUME_SETTLE_S)
        async with self._lock:
            done = self._pin("resume", force_write=True)
        await asyncio.sleep(RESUME_SETTLE_S)
        if self.active and self._failsafe_tripped():
            async with self._lock:
                done = self._pin("resume-failsafe", force_write=True)
            logger.warning("[fan] fans still in failsafe after resume, re-pinned")
        self._last_event = f"resume: {done}"
        logger.info("[fan] %s", self._last_event)

    # ------------------------------------------------------------- actions
    async def restore_factory(self) -> None:
        """Forget the curve of the current profile and pin the factory one again."""
        async with self._lock:
            curves = self.snapshots()
            curves.pop(self.profile(), None)
            self.update_cfg({"curves": curves})
            if self.enabled:
                self._last_event = self._pin("factory-restore", force_write=True)

    async def set_curve(self, curve: Dict[str, Any]) -> None:
        """Custom curve for the current profile; pinned right away."""
        if not self.enabled:
            raise RuntimeError("turn fan curve pinning on first")
        c = sanitize(curve)
        async with self._lock:
            self._save_snapshot(self.profile(), c)
            self._last_event = self._pin("custom", force_write=True)

    # ------------------------------------------------------------- watchdog
    def _start_watchdog(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._watchdog())

    def _stop_watchdog(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(WATCHDOG_PERIOD_S)
            if not self.active:
                return
            try:
                async with self._lock:
                    if self._failsafe_tripped():
                        done = self._pin("failsafe", force_write=True)
                        logger.warning("[fan] failsafe tripped: %s", done)
                    else:
                        done = self._pin("watchdog")
                if done:
                    self._last_event = done
                    logger.info("[fan] %s", done)
                if done or self.last_error:
                    self.last_error = ""
                    await self.notify()
            except Exception as e:  # noqa: BLE001
                logger.exception("[fan] watchdog failed")
                self.last_error = str(e)
                await self.notify()
