"""Suspend/resume detection without Steam client hooks.

From Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT). CLOCK_MONOTONIC stops during
suspend, CLOCK_BOOTTIME does not; a jump in their difference means the machine slept.
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
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        last = self._delta()
        while True:
            await asyncio.sleep(POLL_S)
            now = self._delta()
            slept, last = now - last, now
            if slept >= THRESHOLD_S:
                logger.info("resume detected: suspended for ~%.0fs", slept)
                try:
                    await self._on_resume(slept)
                except Exception:  # noqa: BLE001
                    logger.exception("resume handler failed")
