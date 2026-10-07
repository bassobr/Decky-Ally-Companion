"""Lighting: the RGB rings around the sticks.

Static colours go through the kernel's multicolour LED class (`ally:rgb:joystick_rings`, four
zones, packed 0xRRGGBB intensities, brightness 0..255); the driver restores them after resume.
Linux 7.2 (SteamOS 3.9) caps every intensity at `multi_max_intensity` (255), which leaves only the
blue byte of a packed colour. There static colours go to the MCU like the effects, with the
brightness folded into the colour, and the driver's own copy is set to black so that its restore
after resume cannot paint the rings blue.
Animated modes use the MCU's own effects: `5A B3 <zone> <mode> R G B <speed> <dir> 00 R2 G2 B2`,
then `5A B4` (apply) and `5A B5` (set), with the brightness level 0..3 from `5A BA C5 C4 <level>`.
That packet layout is the one Handheld Daemon documents for the Ally.

The battery mode colours the rings by charge level (red pulse below 15 %) and follows power
supply events.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import threading
from typing import Any, Dict, Optional, Tuple

from .. import ally_hid, sysfs
from ..log import logger
from ..module import Module, cancel_task
from .battery import BAT

LED_DIR = "sys/class/leds/ally:rgb:joystick_rings"
ZONES = 4
MODES = ("off", "static", "breathing", "cycle", "rainbow", "battery")
EC_MODES = {"static": 0x00, "breathing": 0x01, "cycle": 0x02, "rainbow": 0x03}
SPEEDS = {"low": 0xE1, "medium": 0xEB, "high": 0xF5}
LOW_BATTERY = 15
BATTERY_POLL_S = 60.0
RESUME_DELAYS_S = (2.0, 4.0)
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_color(value: Any, fallback: str = "#ffffff") -> Tuple[int, int, int]:
    m = _HEX.match(str(value or "")) or _HEX.match(fallback)
    assert m
    n = int(m.group(1), 16)
    return (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF


def clean_values(values: Any) -> Dict[str, Any]:
    """Lighting values from the UI, a game profile or settings.json; invalid ones are dropped."""
    out: Dict[str, Any] = {}
    if not isinstance(values, dict):
        return out
    if values.get("mode") in MODES:
        out["mode"] = values["mode"]
    for k in ("color", "color2"):
        m = _HEX.match(values[k]) if isinstance(values.get(k), str) else None
        if m:
            out[k] = "#" + m.group(1).lower()
    b = values.get("brightness")
    if isinstance(b, (int, float)) and not isinstance(b, bool) and math.isfinite(b):
        out["brightness"] = max(0, min(100, int(b)))
    if values.get("speed") in SPEEDS:
        out["speed"] = values["speed"]
    return out


def packed_rgb_supported() -> bool:
    """Whether multi_intensity can hold packed 0xRRGGBB values (no cap below 24 bits)."""
    raw = sysfs.read_str(sysfs.p(f"{LED_DIR}/multi_max_intensity"))
    if not raw:
        return True  # before Linux 7.2: no cap
    try:
        return min(int(x) for x in raw.split()) >= 0xFFFFFF
    except ValueError:
        return True


def scale(rgb: Tuple[int, int, int], brightness: int) -> Tuple[int, int, int]:
    return tuple(round(c * max(0, min(100, brightness)) / 100) for c in rgb)  # type: ignore[return-value]


def battery_color(capacity: int, charging: bool) -> Tuple[Tuple[int, int, int], str]:
    """Colour and EC mode for the battery display: red -> yellow -> green with the charge."""
    c = max(0, min(100, capacity))
    if c <= LOW_BATTERY and not charging:
        return (255, 0, 0), "breathing"
    if c < 50:
        rgb = (255, int(255 * c / 50), 0)
    else:
        rgb = (int(255 * (100 - c) / 50), 255, 0)
    return rgb, ("breathing" if charging else "static")


class Lighting(Module):
    id = "lighting"
    title = "Lighting"
    toggle = True
    defaults = {"enabled": False, "mode": "static", "color": "#ff0040", "color2": "#000000", "brightness": 60,
                "speed": "medium"}

    def __init__(self) -> None:
        super().__init__()
        self._battery_task: Optional[asyncio.Task] = None
        self._resume_task: Optional[asyncio.Task] = None
        self._override: Dict[str, Any] = {}  # per-game values from the profiles module
        self._shown = ""
        self._hw_lock = threading.Lock()  # one packet sequence to the MCU at a time, whichever thread

    # ------------------------------------------------------------- settings
    def normalize(self, cfg: Dict[str, Any]) -> None:
        clean = clean_values(cfg)
        for k in ("mode", "color", "color2", "brightness", "speed"):
            cfg[k] = clean.get(k, self.defaults[k])

    def effective(self) -> Dict[str, Any]:
        out = {k: self.cfg.get(k, v) for k, v in self.defaults.items()}
        out.update(self._override)
        return out

    def set_options(self, opts: Dict[str, Any]) -> bool:
        values = clean_values(opts)
        if values:
            self.update_cfg(values)
        return bool(values)

    async def set_override(self, values: Optional[Dict[str, Any]]) -> None:
        """Per-game values (profiles module); None clears them."""
        new = clean_values(values)
        if new != self._override:
            self._override = new
            await self.reapply_if_enabled()

    # ------------------------------------------------------------- module interface
    def supported(self) -> Tuple[bool, str]:
        if not os.path.isdir(sysfs.p(LED_DIR)):
            return False, "joystick LED rings not found (hid_asus_ally)"
        return True, ""

    def is_applied(self) -> bool:
        return bool(self._shown)

    async def apply(self) -> None:
        async with self._lock:  # resume, game profiles and the UI may apply at the same time
            eff = self.effective()
            mode = eff["mode"]
            await self._stop_battery()
            if mode == "battery":
                self._battery_task = asyncio.get_running_loop().create_task(self._battery_loop())
                return
            await asyncio.to_thread(self._show, mode, parse_color(eff["color"]), parse_color(eff["color2"], "#000000"),
                                    int(eff["brightness"]), str(eff["speed"]))

    async def revert(self) -> None:
        async with self._lock:
            await self._stop_battery()
            self._shown = ""  # the rings keep their last state; nothing to restore

    def details(self) -> Dict[str, Any]:
        eff = self.effective()
        return {**eff, "shown": self._shown, "override": bool(self._override),
                "brightnessRaw": sysfs.read_int(sysfs.p(f"{LED_DIR}/brightness")),
                "intensity": sysfs.read_str(sysfs.p(f"{LED_DIR}/multi_intensity"))}

    async def start(self) -> None:
        await self.reapply_if_enabled()
        if self.ctx and self.ctx.uevent:
            self.ctx.uevent.subscribe("power_supply", self._on_power)
            self.ctx.uevent.subscribe("leds", self._on_led)

    async def stop(self) -> None:
        if self.ctx and self.ctx.uevent:
            self.ctx.uevent.unsubscribe("power_supply", self._on_power)
            self.ctx.uevent.unsubscribe("leds", self._on_led)
        await self._stop_battery()
        await cancel_task(self._resume_task)

    async def _on_led(self, event: Dict[str, str]) -> None:
        """The driver re-created the rings (the controller re-enumerated): they show its default."""
        if event.get("ACTION") == "add" and LED_DIR.rsplit("/", 1)[-1] in event.get("DEVPATH", ""):
            await self.on_resume(0.0)  # re-applied a moment later, as after sleep

    async def on_resume(self, slept_s: float) -> None:
        if self.enabled and (self._resume_task is None or self._resume_task.done()):
            self._resume_task = asyncio.get_running_loop().create_task(self._after_resume())

    async def _after_resume(self) -> None:
        for delay in RESUME_DELAYS_S:  # the MCU comes back at an unpredictable moment
            await asyncio.sleep(delay)
            if self.enabled and self.effective()["mode"] != "battery":
                await self.reapply_if_enabled()

    # ------------------------------------------------------------- hardware
    def _write_static(self, rgb: Tuple[int, int, int], brightness: int) -> None:
        if not packed_rgb_supported():
            path = sysfs.p(f"{LED_DIR}/multi_intensity")
            if sysfs.read_str(path) != " ".join(["0"] * ZONES):
                sysfs.write_str(path, " ".join(["0"] * ZONES))
            self._write_ec("static", scale(rgb, brightness), (0, 0, 0), 100 if brightness > 0 else 0, "medium")
            return
        if self._shown and not self._shown.startswith(("static", "off")):
            # stop the MCU animation before the driver takes over again
            try:
                self._write_ec("static", rgb, (0, 0, 0), brightness, "medium")
            except OSError as e:
                logger.warning("[lighting] could not stop the MCU effect: %s", e)
        packed = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
        sysfs.write_str(sysfs.p(f"{LED_DIR}/multi_intensity"), " ".join([str(packed)] * ZONES))
        sysfs.write_str(sysfs.p(f"{LED_DIR}/brightness"), str(round(255 * brightness / 100)))

    def _write_ec(self, mode: str, rgb: Tuple[int, int, int], rgb2: Tuple[int, int, int], brightness: int,
                  speed: str) -> None:
        level = 0 if brightness <= 0 else min(3, 1 + brightness * 3 // 101)
        ally_hid.send_raw(bytes([ally_hid.REPORT_ID, 0xBA, 0xC5, 0xC4, level]))
        packet = bytes([ally_hid.REPORT_ID, 0xB3, 0x00, EC_MODES[mode], *rgb, SPEEDS.get(speed, 0xEB), 0x00, 0x00, *rgb2])
        ally_hid.send_raw(packet)
        ally_hid.send_raw(bytes([ally_hid.REPORT_ID, 0xB4]))
        ally_hid.send_raw(bytes([ally_hid.REPORT_ID, 0xB5]))

    def _show(self, mode: str, rgb: Tuple[int, int, int], rgb2: Tuple[int, int, int], brightness: int, speed: str) -> None:
        # A cancelled caller leaves its thread running: the lock keeps two sequences from interleaving.
        with self._hw_lock:
            if mode == "off" or brightness <= 0:
                self._write_static((0, 0, 0), 0)
            elif mode == "static":
                self._write_static(rgb, brightness)
            else:
                self._write_ec(mode, rgb, rgb2, brightness, speed)
            shown = f"{mode} #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x} {brightness}%"
            if shown != self._shown:
                logger.info("[lighting] %s", shown)
            self._shown = shown

    # ------------------------------------------------------------- battery mode
    def _battery_state(self) -> Tuple[int, bool]:
        cap = sysfs.read_int(sysfs.p(f"{BAT}/capacity"), 50) or 0
        status = sysfs.read_str(sysfs.p(f"{BAT}/status"), "") or ""
        return cap, status in ("Charging", "Full") and cap < 100

    async def _battery_loop(self) -> None:
        last = None
        while True:
            cap, charging = self._battery_state()
            rgb, mode = battery_color(cap, charging)
            key = (rgb, mode)
            if key != last:
                eff = self.effective()
                try:
                    await asyncio.to_thread(self._show, mode, rgb, (0, 0, 0), int(eff["brightness"]), "low")
                    last = key
                except OSError as e:
                    logger.warning("[lighting] battery display failed: %s", e)
            await asyncio.sleep(BATTERY_POLL_S)

    async def _stop_battery(self) -> None:
        await cancel_task(self._battery_task)
        self._battery_task = None

    async def _on_power(self, event: Dict[str, str]) -> None:
        if self.enabled and self.effective()["mode"] == "battery":
            async with self._lock:
                await self._stop_battery()
                self._battery_task = asyncio.get_running_loop().create_task(self._battery_loop())
