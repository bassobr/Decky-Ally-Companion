"""Which device this is and which system interfaces it offers."""
from __future__ import annotations

import glob
import os
import re
from typing import Any, Dict, Optional

from . import dbus, paths
from .constants import BOARDS, INPUTPLUMBER_BUS, INPUTPLUMBER_MANAGER, STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH
from .util import read_text

ALLY_DRIVER_GLOB = "sys/module/hid_asus_ally/drivers/hid:asus_rog_ally/*/mcu_version"
LED_DIR = "sys/class/leds/ally:rgb:joystick_rings"
ARMOURY_DIR = "sys/class/firmware-attributes/asus-armoury/attributes"


ENHANCED_VIBRATION_BOARDS = ("RC73XA", "RC73YA", "RC72LA")  # MCU knows Enhanced Vibration (5A D1 1F)
IMPULSE_TRIGGER_BOARDS = ("RC73XA",)  # motors in the triggers
CAP_HOLDS_BOARDS = ("RC72LA",)  # frequency cap measured to survive charger plug/unplug


def board() -> str:
    return read_text(paths.sys_path("sys/class/dmi/id/board_name"), "") or ""


def model_name(b: Optional[str] = None) -> Optional[str]:
    return BOARDS.get(b if b is not None else board())


def supported() -> bool:
    return board() in BOARDS


def has_enhanced_vibration() -> bool:
    return board() in ENHANCED_VIBRATION_BOARDS


def has_impulse_triggers() -> bool:
    return board() in IMPULSE_TRIGGER_BOARDS


def cap_holds_on_charger() -> bool:
    return board() in CAP_HOLDS_BOARDS


def ally_config_dir() -> Optional[str]:
    """sysfs directory of the controller's config interface (hid_asus_ally), if bound."""
    hits = sorted(glob.glob(paths.sys_path(ALLY_DRIVER_GLOB)))
    return os.path.dirname(hits[0]) if hits else None


def mcu_version(cfg: Optional[str]) -> Optional[str]:
    """The driver reports 0 when it could not read the version from the MCU."""
    v = read_text(os.path.join(cfg, "mcu_version")) if cfg else None
    return v if v and v != "0" else None


def os_release() -> Dict[str, str]:
    out: Dict[str, str] = {}
    text = read_text(paths.sys_path("etc/os-release"), "") or ""
    for line in text.splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def kernel() -> str:
    return read_text(paths.sys_path("proc/sys/kernel/osrelease"), "") or ""


def bios_version() -> str:
    return read_text(paths.sys_path("sys/class/dmi/id/bios_version"), "") or ""


def info() -> Dict[str, Any]:
    b = board()
    rel = os_release()
    cfg = ally_config_dir()
    return {
        "board": b,
        "model": model_name(b),
        "supported": b in BOARDS,
        "bios": bios_version(),
        "mcu": mcu_version(cfg),
        "os": rel.get("PRETTY_NAME") or rel.get("NAME") or "",
        "osId": rel.get("ID", ""),
        "osVersion": rel.get("VERSION_ID", ""),
        "osBuild": rel.get("BUILD_ID", ""),
        "kernel": kernel(),
    }


def stack() -> Dict[str, Any]:
    """System services the modules build on."""
    ip_version = dbus.try_get_property(INPUTPLUMBER_BUS, INPUTPLUMBER_MANAGER, "org.shadowblip.InputManager", "Version")
    model = dbus.try_get_property(STEAMOS_MANAGER_BUS, STEAMOS_MANAGER_PATH,
                                  f"{STEAMOS_MANAGER_BUS}.Manager2", "DeviceModel", user_bus=True)
    return {
        "inputplumber": {"present": ip_version is not None, "version": ip_version},
        "steamosManager": {"present": model is not None, "deviceModel": model},
        "hidAsusAlly": ally_config_dir() is not None,
        "led": os.path.isdir(paths.sys_path(LED_DIR)),
        "asusArmoury": os.path.isdir(paths.sys_path(ARMOURY_DIR)),
    }
