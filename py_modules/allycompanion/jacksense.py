"""Headphone jack from the codec's input device: switch events instead of polling PipeWire.

The HDA driver exposes the jack as an input device ("HD-Audio Generic Headphone" on both Allys)
that reports SW_HEADPHONE_INSERT. Subscribers are called on every change; PipeWire moves the
output route a moment later, so they re-check the route themselves. Without the device the audio
modules fall back to polling.
"""
from __future__ import annotations

import asyncio
import fcntl
import glob
import os
import struct
from typing import Awaitable, Callable, List, Optional

from . import paths
from .log import logger
from .module import spawn
from .util import read_text

EV_SW = 0x05
SW_HEADPHONE_INSERT = 0x02
EVENT = struct.Struct("llHHi")  # struct input_event: timeval, type, code, value
EVIOCGSW = 0x80000000 | (8 << 16) | (ord("E") << 8) | 0x1B  # switch state, 8 bytes

Callback = Callable[[bool], Awaitable[None]]


def find_device() -> Optional[str]:
    """/dev/input node of the headphone jack switch, if the codec has one."""
    for ev in sorted(glob.glob(paths.sys_path("sys/class/input/event*"))):
        name = read_text(os.path.join(ev, "device", "name"), "") or ""
        words = (read_text(os.path.join(ev, "device", "capabilities", "sw"), "") or "").split()
        try:
            sw = int(words[-1], 16) if words else 0
        except ValueError:
            continue
        if "Headphone" in name and sw & (1 << SW_HEADPHONE_INSERT):
            return "/dev/input/" + os.path.basename(ev)
    return None


def parse(data: bytes) -> Optional[bool]:
    """The last headphone switch value in a batch of input events, None if there is none."""
    state = None
    for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
        _, _, typ, code, value = EVENT.unpack_from(data, off)
        if typ == EV_SW and code == SW_HEADPHONE_INSERT:
            state = bool(value)
    return state


class JackSense:
    def __init__(self) -> None:
        self.path: Optional[str] = None
        self.inserted: Optional[bool] = None
        self._fd: Optional[int] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subs: List[Callback] = []

    @property
    def available(self) -> bool:
        return self._fd is not None

    def subscribe(self, cb: Callback) -> None:
        self._subs.append(cb)

    def unsubscribe(self, cb: Callback) -> None:
        if cb in self._subs:
            self._subs.remove(cb)

    def start(self) -> None:
        if self._fd is not None:
            return
        path = find_device()
        if path is None:
            logger.info("headphone jack switch not found; jack changes are polled")
            return
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
        except OSError as e:
            logger.warning("headphone jack switch %s not opened: %s", path, e)
            return
        self._loop = asyncio.get_running_loop()
        self._fd, self.path = fd, path
        self.inserted = self._query()
        self._loop.add_reader(fd, self._on_readable)
        logger.info("headphone jack switch %s (%s)", path, "plugged" if self.inserted else "empty")

    def stop(self) -> None:
        if self._fd is None:
            return
        if self._loop is not None:
            self._loop.remove_reader(self._fd)
        os.close(self._fd)
        self._fd = None

    def _query(self) -> Optional[bool]:
        buf = bytearray(8)
        try:
            fcntl.ioctl(self._fd, EVIOCGSW, buf)  # type: ignore[arg-type]
        except OSError:
            return None
        return bool(buf[0] & (1 << SW_HEADPHONE_INSERT))

    def _on_readable(self) -> None:
        state = None
        try:
            while True:
                data = os.read(self._fd, EVENT.size * 64)  # type: ignore[arg-type]
                if not data:
                    break
                found = parse(data)
                state = found if found is not None else state
        except BlockingIOError:
            pass
        except OSError as e:  # the device went away (driver rebind): back to polling
            logger.warning("headphone jack switch lost: %s", e)
            self.stop()
            return
        if state is None or state == self.inserted:
            return
        self.inserted = state
        logger.info("headphones %s", "plugged in" if state else "unplugged")
        for cb in list(self._subs):
            spawn(self._safe(cb, state))

    @staticmethod
    async def _safe(cb: Callback, state: bool) -> None:
        try:
            await cb(state)
        except Exception:  # noqa: BLE001
            logger.exception("headphone jack subscriber failed")
