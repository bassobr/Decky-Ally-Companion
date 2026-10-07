"""Suspend/resume detection without Steam client hooks.

From Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT). CLOCK_MONOTONIC stops during
suspend, CLOCK_BOOTTIME does not; a jump in their difference means the machine slept.
A timer callback rather than a task: Decky closes the loop right after the plugin's _unload, and a
task cancelled there could never finish ("Task was destroyed but it is pending!").
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from .log import logger

POLL_S = 1.0
THRESHOLD_S = 0.2  # the difference only moves during suspend, so any jump is a resume


def boot_mono_delta() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


class ResumeDetector:
    def __init__(self, on_resume: Callable[[float], Awaitable[None]],
                 delta: Callable[[], float] = boot_mono_delta) -> None:
        self._on_resume = on_resume
        self._delta = delta
        self._timer: Optional[asyncio.TimerHandle] = None
        self._handler: Optional[asyncio.Task] = None
        self._last = 0.0

    def start(self) -> None:
        if self._timer is None:
            self._last = self._delta()
            self._schedule()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self) -> None:
        self._timer = asyncio.get_running_loop().call_later(POLL_S, self._tick)

    def _tick(self) -> None:
        try:
            # One resume at a time: a suspend during the handler shows up in the first tick after it.
            if self._handler is None or self._handler.done():
                now = self._delta()
                slept, self._last = now - self._last, now
                if slept >= THRESHOLD_S:
                    logger.info("resume detected: suspended for ~%.0fs", slept)
                    self._handler = asyncio.get_running_loop().create_task(self._notify(slept))
        finally:
            self._schedule()

    async def _notify(self, slept: float) -> None:
        try:
            await self._on_resume(slept)
        except Exception:  # noqa: BLE001
            logger.exception("resume handler failed")
