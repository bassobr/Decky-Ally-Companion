"""Kernel uevent listener over netlink (no udev dependency).

From Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT). Subscribers register a callback
for a SUBSYSTEM value and receive the parsed event (ACTION, SUBSYSTEM, DEVPATH and env keys).
"""
from __future__ import annotations

import asyncio
import socket
from typing import Awaitable, Callable, Dict, List, Optional

from .log import logger
from .module import spawn

NETLINK_KOBJECT_UEVENT = 15
GROUP_KERNEL = 1

Callback = Callable[[Dict[str, str]], Awaitable[None]]


def parse(data: bytes) -> Optional[Dict[str, str]]:
    # "action@devpath\0KEY=VAL\0KEY=VAL\0..."; udev-processed events carry a binary header
    if data.startswith(b"libudev"):
        return None
    parts = data.split(b"\0")
    if not parts or b"@" not in parts[0]:
        return None
    event: Dict[str, str] = {}
    for part in parts[1:]:
        if b"=" in part:
            k, v = part.split(b"=", 1)
            event[k.decode(errors="replace")] = v.decode(errors="replace")
    return event


class UeventMonitor:
    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._subs: Dict[str, List[Callback]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def subscribe(self, subsystem: str, cb: Callback) -> None:
        self._subs.setdefault(subsystem, []).append(cb)

    def unsubscribe(self, subsystem: str, cb: Callback) -> None:
        try:
            self._subs.get(subsystem, []).remove(cb)
        except ValueError:
            pass

    def start(self) -> None:
        if self._sock is not None:
            return
        self._loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_KOBJECT_UEVENT)
        sock.setblocking(False)
        sock.bind((0, GROUP_KERNEL))
        self._sock = sock
        self._loop.add_reader(sock.fileno(), self._on_readable)

    def stop(self) -> None:
        if self._sock is None:
            return
        if self._loop is not None:
            self._loop.remove_reader(self._sock.fileno())
        self._sock.close()
        self._sock = None

    def _on_readable(self) -> None:
        assert self._sock is not None
        try:
            while True:
                data = self._sock.recv(8192)
                if not data:
                    return
                event = parse(data)
                if event:
                    self.dispatch(event)
        except BlockingIOError:
            return
        except OSError as e:
            logger.warning("uevent recv failed: %s", e)

    def dispatch(self, event: Dict[str, str]) -> None:
        for cb in list(self._subs.get(event.get("SUBSYSTEM", ""), [])):
            spawn(self._safe(cb, event))

    @staticmethod
    async def _safe(cb: Callback, event: Dict[str, str]) -> None:
        try:
            await cb(event)
        except Exception:  # noqa: BLE001
            logger.exception("uevent subscriber failed for %s", event.get("SUBSYSTEM"))
