"""Pause the chain while headphones use the shared analog sink.

With jack events (the backend's jacksense calls kick()) the route is checked right after each
plug or unplug and otherwise only once a minute; without them it is polled every few seconds.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from . import dsp_runtime, hardware
from .log import logger

IDLE_S = 60.0  # safety re-check while jack events drive the checks
BURST_S, BURST_STEP_S = 3.0, 0.5  # PipeWire moves the route a moment after the jack event


class JackWatcher:
    def __init__(self, interval: float = 3.0, on_change: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.interval = interval
        self.on_change = on_change
        self.headphones: Optional[bool] = None
        self.event_driven: Callable[[], bool] = lambda: False  # asked each time: the event source can go away
        self._task: Optional[asyncio.Task] = None
        self._wake: Optional[asyncio.Event] = None
        self._burst_until = 0.0

    @property
    def paused(self) -> bool:
        """The chain stays off while headphones use the shared sink, whoever stopped it."""
        return bool(self.headphones)

    def state(self) -> Dict[str, Any]:
        return {"headphones": self.headphones, "paused": self.paused}

    def start(self, should_run: Callable[[], bool]) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run(should_run))

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def kick(self) -> None:
        """A jack event or a resume: check now and a few times right after."""
        self._burst_until = time.monotonic() + BURST_S
        if self._wake is not None:
            self._wake.set()

    def next_delay(self) -> float:
        if time.monotonic() < self._burst_until:
            return BURST_STEP_S
        return IDLE_S if self.event_driven() else self.interval

    async def poll(self, should_run: Callable[[], bool]) -> None:
        dump = await asyncio.to_thread(hardware.pw_dump)
        if not dump:
            return
        hp = hardware.headphones_active(hardware.output_route(dump))
        if hp == self.headphones:
            return
        first = self.headphones is None  # the backend's startup reconcile starts the chain
        self.headphones = hp
        if hp:
            if await asyncio.to_thread(dsp_runtime.is_active):
                await asyncio.to_thread(dsp_runtime.stop)
                logger.info("headphones detected: chain paused")
        elif not first and should_run() and not await asyncio.to_thread(dsp_runtime.is_active):
            await asyncio.to_thread(dsp_runtime.start)
            logger.info("headphones removed: chain resumed")
        if self.on_change:
            res = self.on_change(self.state())
            if asyncio.iscoroutine(res):
                await res

    async def run(self, should_run: Callable[[], bool]) -> None:
        self._wake = asyncio.Event()
        while True:
            try:
                await self.poll(should_run)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("jack watcher: %s", e)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.next_delay())
            except asyncio.TimeoutError:
                pass
