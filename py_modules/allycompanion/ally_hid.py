"""The controller's MCU: config interface discovery and feature-report commands.

Command format from hid-asus-ally.h, as used by Ally Fix (https://github.com/lonsdaleite/Ally-Fix,
MIT): report 0x5A, class byte, command, payload length, payload. The MCU echoes the last accepted
command through a GET of the same feature report; rumble traffic shares that echo, so an
unconfirmed send is retried a few times.
"""
from __future__ import annotations

import fcntl
import glob
import os
from typing import Optional

from . import sysfs

DRIVER_DIR_GLOB = "sys/module/hid_asus_ally/drivers/hid:asus_rog_ally/*/vibration_intensity"
HIDRAW_ATTR_GLOB = "sys/class/hidraw/*/device/vibration_intensity"

REPORT_ID = 0x5A
XPAD_CONFIG = 0xD1
REPORT_SIZE = 64
HIDIOCSFEATURE = 0xC0000000 | (REPORT_SIZE << 16) | (ord("H") << 8) | 0x06
HIDIOCGFEATURE = 0xC0000000 | (REPORT_SIZE << 16) | (ord("H") << 8) | 0x07
ECHO_TRIES = 3


def config_dir() -> Optional[str]:
    """sysfs directory of the config interface (the one with vibration_intensity)."""
    for pattern in (DRIVER_DIR_GLOB, HIDRAW_ATTR_GLOB):
        found = sysfs.sorted_glob(pattern)
        if found:
            return os.path.dirname(found[0])
    return None


def attr(name: str) -> Optional[str]:
    d = config_dir()
    return os.path.join(d, name) if d else None


def hidraw_node() -> Optional[str]:
    d = config_dir()
    nodes = sorted(glob.glob(os.path.join(d, "hidraw", "hidraw*"))) if d else []
    return "/dev/" + os.path.basename(nodes[0]) if nodes else None


def send(cls: int, cmd: int, data: bytes) -> bool:
    """Send `5A <cls> <cmd> <len> <data>`; returns whether the echo confirmed it. Raises OSError
    when the device cannot be written."""
    node = hidraw_node()
    if node is None:
        raise OSError("hidraw node of the controller config interface not found")
    packet = bytes([REPORT_ID, cls, cmd, len(data)]) + data
    fd = os.open(node, os.O_RDWR)
    try:
        for _ in range(ECHO_TRIES):
            buf = bytearray(REPORT_SIZE)
            buf[: len(packet)] = packet
            fcntl.ioctl(fd, HIDIOCSFEATURE, buf)
            echo = bytearray(REPORT_SIZE)
            echo[0] = REPORT_ID
            try:
                fcntl.ioctl(fd, HIDIOCGFEATURE, echo)
            except OSError:
                return False  # echo unreadable; the SET itself went through
            if bytes(echo[: len(packet)]) == packet:
                return True
    finally:
        os.close(fd)
    return False


def send_raw(packet: bytes) -> None:
    """One feature report as given (padded to the report size); no echo check."""
    node = hidraw_node()
    if node is None:
        raise OSError("hidraw node of the controller config interface not found")
    buf = bytearray(REPORT_SIZE)
    buf[: len(packet)] = packet
    fd = os.open(node, os.O_RDWR)
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE, buf)
    finally:
        os.close(fd)


def send_xpad(cmd: int, data: bytes) -> bool:
    return send(XPAD_CONFIG, cmd, data)
