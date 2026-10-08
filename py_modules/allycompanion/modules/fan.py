"""Fans: pin the fan curve so the EC cannot get stuck at full speed, plus custom curves.

The pinning is ported from the Fan Noise Fix of Ally Fix (https://github.com/lonsdaleite/Ally-Fix,
MIT). Occasionally after resume both fans spin at maximum and never settle; writing the curve with
pwm*_enable=1 brings the EC back. asus-wmi resets pwm*_enable to 2 on every thermal-profile change
and never restores curves after resume, so a watchdog keeps the curve pinned.

For each thermal profile the module pins the curve that is there: the factory curve of that
profile (loaded through pwm_enable=3) or whatever another tool wrote while pinned. A custom curve
set in the UI replaces the remembered curve of the current profile.

SteamOS 3.9.2 works around the firmware bug after sleep itself. From that version on the pinning
stays off whatever the setting says (the setting is kept for older versions); a game profile's
curve is still pinned while the game runs.

No curve goes below the factory curve of the active thermal profile from 85 °C on (custom, game
and remembered curves alike): below that a curve may be as quiet as wanted, but a curve with the
fans off at any temperature cannot reach the EC, whether it comes from the UI, settings.json or a
backup. The factory curve is read from the EC (pwm_enable=3) and kept in memory only.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

from .. import device, sysfs
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
FIXED_IN_STEAMOS = (3, 9, 2)
NOT_NEEDED = "Not needed since SteamOS 3.9.2, which fixes the fan speed after sleep itself"
TEMP_RANGE = (20, 110)
FLOOR_FROM_C = 85
FLOOR_TEMPS = (85, 90, 95, 100, 105, 110)

Curve = Dict[str, List[int]]  # {"temps": [...], "pwm1": [...], "pwm2": [...]}


def fixed_by_os() -> bool:
    v = device.steamos_version()
    return v is not None and v >= FIXED_IN_STEAMOS


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
        raw = curve.get(key)
        if not isinstance(raw, list) or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in raw):
            raise ValueError(f"{key} needs {POINTS} numbers")
        vals = [max(lo, min(hi, int(v))) for v in raw]
        if len(vals) != POINTS:
            raise ValueError(f"{key} needs {POINTS} points")
        for i in range(1, POINTS):
            vals[i] = max(vals[i], vals[i - 1])
        out[key] = vals
    if out["temps"][0] > FLOOR_FROM_C:
        raise ValueError(f"the curve has to start at {FLOOR_FROM_C} °C or below")
    return out


def duty_at(curve: Curve, fan: str, temp: int) -> int:
    """Duty the curve gives at `temp`: each point holds until the next one, the last one beyond."""
    duty = 0
    for t, d in zip(curve["temps"], curve[fan]):
        if t <= temp:
            duty = d
    return duty


def apply_floor(curve: Curve, factory: Curve) -> Curve:
    """`curve`, raised where it would give less than the factory curve from FLOOR_FROM_C on."""
    out: Curve = {k: list(v) for k, v in curve.items()}
    for fan in FANS:
        for temp in FLOOR_TEMPS:
            need = duty_at(factory, fan, temp)
            below = [i for i, t in enumerate(out["temps"]) if t <= temp]
            if below and out[fan][below[-1]] < need:
                for j in range(below[-1], POINTS):
                    out[fan][j] = max(out[fan][j], need)
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
        self._factory: Dict[str, Curve] = {}  # per thermal profile, read from the EC; never from a file

    def normalize(self, cfg: Dict[str, Any]) -> None:
        curves: Dict[str, Curve] = {}
        raw = cfg.get("curves")
        for profile, curve in (raw.items() if isinstance(raw, dict) else []):
            if isinstance(profile, str) and len(profile) <= 32:
                try:
                    curves[profile] = sanitize(curve)
                except (TypeError, ValueError):
                    pass
        cfg["curves"] = curves

    @property
    def pinning(self) -> bool:
        """The fix itself: the setting, unless SteamOS handles the firmware bug."""
        return self.enabled and not fixed_by_os()

    @property
    def active(self) -> bool:
        return self.pinning or self._override is not None

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
        if on and fixed_by_os():
            raise RuntimeError(NOT_NEEDED)
        self.update_cfg({"enabled": bool(on)})
        self.last_error = ""
        try:
            await (self.apply() if self.active else self.revert())
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] %s failed", self.id, "apply" if self.active else "revert")
            self.last_error = str(e)

    async def set_override(self, values: Optional[Dict[str, Any]]) -> None:
        """Game profile {"curve": {...}}; None goes back to the pinned or firmware curve."""
        new = sanitize(values["curve"]) if isinstance(values, dict) and values.get("curve") else None
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

    def _capture_factory(self, profile: str) -> Curve:
        """The EC's factory curve of the active thermal profile; pwm_enable=3 loads it."""
        self._write_enable(3)
        curve = self.read_curve()
        if not valid(curve):
            raise OSError("factory fan curve unreadable")
        self._factory[profile] = curve
        return curve

    def _floored(self, curve: Curve, profile: str) -> Curve:
        return apply_floor(curve, self._factory.get(profile) or self._capture_factory(profile))

    def _pin(self, reason: str, force_write: bool = False) -> str:
        """Ensure the current profile's curve is loaded and enabled; returns what was done."""
        profile = self.profile()
        en1, en2 = self.enable_state()
        curve = self.read_curve()
        if self._override is not None:
            captured = profile not in self._factory  # capturing resets the EC's curve
            target = self._floored(self._override, profile)
            if captured or force_write or en1 != 1 or en2 != 1 or curve != target:
                self._write_curve(target)
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
            curve = self._capture_factory(profile)
            self._save_snapshot(profile, curve)
            action = f"captured factory curve for {profile}"
        else:
            curve = self._floored(snap, profile)  # type: ignore[arg-type]
            if curve != snap:
                self._save_snapshot(profile, curve)
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

    def refine(self, state: str, message: str, details: Dict[str, Any]) -> Tuple[str, str]:
        if details.get("fixedByOs") and state in ("applied", "not_applied") and self._override is None:
            return "info", NOT_NEEDED
        return state, message

    async def apply(self) -> None:
        self._start_watchdog()
        async with self._lock:
            done = self._pin("apply")
        self._last_event = done or "pinned"
        logger.info("[fan] %s", self._last_event)

    async def revert(self) -> None:
        self._stop_watchdog()
        async with self._lock:
            self._write_enable(3)  # firmware auto, with the factory curve back in the custom registers
        self._last_event = "unpinned"
        logger.info("[fan] curve unpinned (firmware auto, factory curve)")

    def details(self) -> Dict[str, Any]:
        profile = self.profile()
        cur: Optional[Curve] = None
        try:
            cur = self.read_curve()
        except OSError:
            pass
        return {"profile": profile, "pwmEnable": list(self.enable_state()), "rpm": list(self.rpm()), "temp": self.temp(),
                "curve": cur, "snapshotProfiles": sorted(self.snapshots()), "lastEvent": self._last_event,
                "override": self._override is not None, "fixedByOs": fixed_by_os(), "floorFromC": FLOOR_FROM_C}

    async def start(self) -> None:
        if self.enabled and not self.active and self.supported()[0] and self.is_applied():
            await self.revert()  # pinned under an older SteamOS; the firmware curve takes over again
        await self.reapply_if_enabled()

    async def stop(self) -> None:
        await cancel_task(self._task)
        self._task = None

    async def on_resume(self, slept_s: float) -> None:
        if not self.active:
            return
        await asyncio.sleep(RESUME_SETTLE_S)
        async with self._lock:
            if not self.active:  # switched off, or the game's curve ended, while the EC settled
                return
            done = self._pin("resume", force_write=True)
        await asyncio.sleep(RESUME_SETTLE_S)
        async with self._lock:
            if self.active and self._failsafe_tripped():
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
            if self.pinning:
                self._last_event = self._pin("factory-restore", force_write=True)

    async def set_curve(self, curve: Dict[str, Any]) -> None:
        """Custom curve for the current profile; pinned right away."""
        if not self.pinning:
            raise RuntimeError(NOT_NEEDED if fixed_by_os() else "turn fan curve pinning on first")
        c = sanitize(curve)
        async with self._lock:
            profile = self.profile()
            self._save_snapshot(profile, self._floored(c, profile))
            self._last_event = self._pin("custom", force_write=True)

    # ------------------------------------------------------------- watchdog
    def _start_watchdog(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._watchdog())

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
