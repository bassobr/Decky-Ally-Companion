"""Vibration: grip-motor intensity, Enhanced Vibration and the rumble packet filter.

Ported from the Vibration Fix of Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT).

The MCU takes intensity as 0..100 per motor (firmware default 100/100) via `5A D1 06`. The
driver's sysfs attribute rejects values above 64 and forwards its copy to the MCU on write, so
the sysfs mirror is written first and the real value goes out last. The controller resets during
suspend (and loses intensity and Enhanced Vibration), at an unpredictable moment after resume,
so after resume and re-enumeration the settings are re-sent as a spaced series.

Enhanced Vibration (Armoury Crate's "Xbox-recommended waveform", `5A D1 1F`) is independent of the
intensity switch. While it is on, a HID-BPF program caps the driver's rumble magnitudes at the
MCU's 100 (the driver sends up to 127, which rattles). "Mirror to triggers" (Xbox Ally X only)
copies grip rumble onto the impulse triggers through the same program.
"""
from __future__ import annotations

import asyncio
import fcntl
import glob
import os
import struct
import time
from typing import Any, Dict, Optional, Tuple

from .. import ally_hid, device, hidbpf, sysfs
from ..log import logger
from ..module import Module, cancel_task

MAX_INTENSITY = 100
SYSFS_MAX = 64  # kernel store handler limit
FACTORY = (MAX_INTENSITY, MAX_INTENSITY)
REBIND_DELAYS_S = (1.0, 2.0, 3.0, 4.0, 5.0)  # cumulative ~1/3/6/10/15 s after the trigger

CMD_SET_INTENSITY = 0x06
CMD_SET_ENHANCED = 0x1F

EVIOCGBIT_FF = 0x80204535
EVIOCSFF = 0x40304580
EVIOCRMFF = 0x40044581
EV_FF = 0x15
FF_RUMBLE = 0x50
ASUS_VENDOR = ":0B05:"


def clamp(v: Any, lo: int = 0, hi: int = MAX_INTENSITY) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


def find_ff_device() -> Optional[str]:
    """An evdev node with FF_RUMBLE, preferring the ASUS gamepad."""
    candidates = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            buf = bytearray(32)
            fcntl.ioctl(fd, EVIOCGBIT_FF, buf)
            if not (buf[FF_RUMBLE // 8] >> (FF_RUMBLE % 8)) & 1:
                continue
        except OSError:
            continue
        finally:
            os.close(fd)
        name = sysfs.read_str(f"/sys/class/input/{os.path.basename(path)}/device/name", "") or ""
        score = 2 if ("ASUS" in name.upper() or "ALLY" in name.upper()) else 1
        candidates.append((score, path))
    return sorted(candidates, reverse=True)[0][1] if candidates else None


def gamepad_hid_id() -> Optional[int]:
    """Numeric hid id of the interface owning the FF evdev node (`0003:0B05:1B4C.0006` -> 6)."""
    ev = find_ff_device()
    if ev is None:
        return None
    name = os.path.basename(os.path.realpath(f"/sys/class/input/{os.path.basename(ev)}/device/device"))
    if ASUS_VENDOR not in name.upper():
        return None  # a virtual pad (uhid) would take the attach and filter nothing
    try:
        return int(name.rsplit(".", 1)[1], 16)
    except (IndexError, ValueError):
        return None


class Vibration(Module):
    id = "vibration"
    title = "Vibration"
    toggle = True
    defaults = {"enabled": False, "left": 50, "right": 50, "linked": True, "enhanced": False, "mirror_triggers": False}

    def __init__(self) -> None:
        super().__init__()
        self._rebind_task: Optional[asyncio.Task] = None
        self._hw: Optional[Tuple[int, int]] = None  # last value sent to the MCU
        self._ff: Optional[hidbpf.FfFilter] = None
        self._ff_error = ""
        self._ff_stale = False  # the hid device was re-created; re-attach even if the id repeats

    # ------------------------------------------------------------- options
    @property
    def intensity(self) -> Tuple[int, int]:
        return clamp(self.cfg.get("left", 50)), clamp(self.cfg.get("right", 50))

    @property
    def enhanced(self) -> bool:
        return bool(self.cfg.get("enhanced")) and device.is_xbox_ally()

    @property
    def mirror_triggers(self) -> bool:
        return bool(self.cfg.get("mirror_triggers")) and device.has_impulse_triggers()

    def set_options(self, opts: Dict[str, Any]) -> bool:
        values: Dict[str, Any] = {}
        if "linked" in opts:
            values["linked"] = bool(opts["linked"])
        for k in ("left", "right"):
            if k in opts:
                values[k] = clamp(opts[k])
        if values.get("linked", self.cfg.get("linked", True)):
            if "left" in values:
                values["right"] = values["left"]
            elif "right" in values:
                values["left"] = values["right"]
        if values:
            self.update_cfg(values)
        return bool(values)

    def actions(self):
        return {"set_enhanced": self.set_enhanced, "set_mirror": self.set_mirror, "test": self.test}

    # ------------------------------------------------------------- module interface
    def supported(self) -> Tuple[bool, str]:
        if ally_hid.attr("vibration_intensity") is None:
            return False, "hid_asus_ally driver not found"
        return True, ""

    def is_applied(self) -> bool:
        return self._read_hw() == self.intensity

    async def apply(self) -> None:
        self._write_hw(*self.intensity)
        logger.info("[vibration] intensity %d/%d", *self.intensity)

    async def revert(self) -> None:
        self._write_hw(*FACTORY)
        logger.info("[vibration] intensity back to factory %d/%d", *FACTORY)

    def details(self) -> Dict[str, Any]:
        hw = self._read_hw()
        left, right = self.intensity
        return {
            "left": left, "right": right, "linked": bool(self.cfg.get("linked", True)),
            "enhanced": self.enhanced, "enhancedSupported": device.is_xbox_ally(),
            "mirrorTriggers": self.mirror_triggers, "mirrorSupported": device.has_impulse_triggers(),
            "hw": list(hw) if hw else None,
            "ffFilter": hidbpf.flags_name(self._ff.flags) if self._ff else "off",
            "ffError": self._ff_error,
        }

    async def start(self) -> None:
        await self.reapply_if_enabled()
        self._resend_enhanced()
        if self.ctx and self.ctx.uevent:
            self.ctx.uevent.subscribe("hid", self._on_hid_event)
        self._sync_ff_filter()

    async def stop(self) -> None:
        if self.ctx and self.ctx.uevent:
            self.ctx.uevent.unsubscribe("hid", self._on_hid_event)
        await cancel_task(self._rebind_task)
        self._rebind_task = None
        self._close_ff()

    async def on_resume(self, slept_s: float) -> None:
        if self._wants_controller():
            self._hw = None
            self._schedule_rebind("resume")

    async def uninstall(self) -> None:
        await super().uninstall()
        # The flag lives in the controller; without the plugin nothing could turn it off.
        if self.cfg.get("enhanced") and device.is_xbox_ally():
            ally_hid.send_xpad(CMD_SET_ENHANCED, b"\x00")
        self._close_ff()

    # ------------------------------------------------------------- actions
    async def set_enhanced(self, on: bool) -> None:
        if not device.is_xbox_ally():
            raise RuntimeError("Enhanced Vibration needs a ROG Xbox Ally")
        confirmed = ally_hid.send_xpad(CMD_SET_ENHANCED, bytes([1 if on else 0]))
        self.update_cfg({"enhanced": bool(on)})
        logger.info("[vibration] enhanced %s%s", "on" if on else "off", "" if confirmed else " (echo unconfirmed)")
        self._sync_ff_filter()

    async def set_mirror(self, on: bool) -> None:
        if not device.has_impulse_triggers():
            raise RuntimeError("Trigger rumble needs a ROG Xbox Ally X")
        self.update_cfg({"mirror_triggers": bool(on)})
        self._sync_ff_filter()
        if on and self._ff_error:
            error = self._ff_error
            self.update_cfg({"mirror_triggers": False})
            self._sync_ff_filter()
            raise OSError(error)

    async def test(self, duration_ms: int = 500) -> None:
        """A short FF_RUMBLE so the current intensity can be felt. 0xC800 goes out as magnitude
        100, the MCU's full scale; 0xFFFF would be sent as 127 and buzz with Enhanced Vibration."""
        duration = max(100, min(2000, int(duration_ms)))
        strong = weak = 100 * 512
        ff_path = find_ff_device()
        if ff_path is None:
            raise OSError("no rumble-capable input device found")
        fd = os.open(ff_path, os.O_RDWR)
        try:
            effect = bytearray(struct.pack("<HhHHHHHxxHH28x", FF_RUMBLE, -1, 0, 0, 0, duration, 0, strong, weak))
            fcntl.ioctl(fd, EVIOCSFF, effect)
            effect_id = struct.unpack_from("<h", effect, 2)[0]

            def ev(value: int) -> bytes:
                t = time.time()
                return struct.pack("<qqHHi", int(t), int((t % 1) * 1e6), EV_FF, effect_id, value)

            os.write(fd, ev(1))
            await asyncio.sleep(duration / 1000.0)
            os.write(fd, ev(0))
            fcntl.ioctl(fd, EVIOCRMFF, effect_id)  # takes the id by value
        finally:
            os.close(fd)

    # ------------------------------------------------------------- hardware
    def _read_hw(self) -> Optional[Tuple[int, int]]:
        if self._hw is not None:
            return self._hw
        path = ally_hid.attr("vibration_intensity")
        raw = sysfs.read_str(path) if path else None
        try:
            left, right = (int(x) for x in (raw or "").split()[:2])
            return left, right
        except ValueError:
            return None

    def _write_hw(self, left: int, right: int) -> None:
        path = ally_hid.attr("vibration_intensity")
        if path is None:
            raise OSError("vibration_intensity attribute not found")
        try:
            sysfs.write_str(path, f"{left} {right}\n")
        except OSError:
            sysfs.try_write(path, "%d %d\n" % (min(left, SYSFS_MAX), min(right, SYSFS_MAX)), "[vibration]")
        confirmed = ally_hid.send_xpad(CMD_SET_INTENSITY, bytes([left, right]))
        self._hw = (left, right)
        if not confirmed:
            logger.warning("[vibration] intensity %d/%d sent, echo unconfirmed", left, right)

    def _resend_enhanced(self) -> None:
        if not self.enhanced or not self.supported()[0]:
            return
        try:
            if not ally_hid.send_xpad(CMD_SET_ENHANCED, b"\x01"):
                logger.warning("[vibration] enhanced re-send, echo unconfirmed")
        except OSError as e:
            logger.warning("[vibration] enhanced re-send failed: %s", e)

    def _wants_controller(self) -> bool:
        return self.enabled or self.enhanced or self.mirror_triggers

    # ------------------------------------------------------------- FF packet filter
    def _ff_flags(self) -> int:
        return (hidbpf.FLAG_CLAMP if self.enhanced else 0) | (hidbpf.FLAG_MIRROR if self.mirror_triggers else 0)

    def _sync_ff_filter(self, force: bool = False) -> None:
        flags = self._ff_flags()
        hid_id = gamepad_hid_id() if flags else None
        cur = self._ff
        force = force or self._ff_stale
        if cur is not None and not force and cur.flags == flags and cur.hid_id == hid_id:
            return
        self._close_ff()
        if not flags:
            self._ff_stale = False
            self._ff_error = ""
            return
        if hid_id is None:
            self._ff_error = "gamepad hid device not found"
            return
        try:
            self._ff = hidbpf.attach(hid_id, flags)
        except Exception as e:  # noqa: BLE001
            self._ff_error = f"rumble filter not loaded: {e}"
            logger.warning("[vibration] %s", self._ff_error)
            return
        self._ff_stale = False
        self._ff_error = ""
        logger.info("[vibration] rumble filter on hid %d (%s)", hid_id, hidbpf.flags_name(flags))

    def _close_ff(self) -> None:
        if self._ff is not None:
            self._ff.close()
            self._ff = None

    # ------------------------------------------------------------- re-enumeration and resume
    async def _on_hid_event(self, event: Dict[str, str]) -> None:
        if not self._wants_controller() or event.get("ACTION") not in ("add", "bind"):
            return
        if "asus" not in event.get("DRIVER", "").lower() and "0B05" not in event.get("HID_ID", "").upper():
            return
        self._hw = None
        self._ff_stale = True
        self._schedule_rebind(f"hid {event.get('ACTION')}")

    def _schedule_rebind(self, reason: str) -> None:
        if self._rebind_task is None or self._rebind_task.done():
            self._rebind_task = asyncio.get_event_loop().create_task(self._rebind(reason))

    async def _rebind(self, reason: str) -> None:
        sent = failed = 0
        for delay in REBIND_DELAYS_S:
            await asyncio.sleep(delay)
            if not self._wants_controller():
                return
            self._sync_ff_filter()
            if not (self.enabled or self.enhanced):
                continue
            try:
                if self.enabled:
                    self._write_hw(*self.intensity)
                if self.enhanced:
                    ally_hid.send_xpad(CMD_SET_ENHANCED, b"\x01")
                sent += 1
            except OSError as e:
                failed += 1
                logger.warning("[vibration] re-apply after %s failed: %s", reason, e)
        if sent:
            self.last_error = ""
            logger.info("[vibration] re-applied after %s (%d/%d sends ok)", reason, sent, sent + failed)
        elif self.enabled or self.enhanced:
            self.last_error = f"could not re-apply vibration settings after {reason}"
        await self.notify()
