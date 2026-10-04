"""Builds the modules, binds their settings sections and fans out lifecycle events."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Type

from .log import logger
from .module import Module


class Registry:
    def __init__(self, classes: List[Type[Module]]) -> None:
        self.modules: Dict[str, Module] = {}
        for cls in classes:
            m = cls()
            if not m.id or m.id in self.modules:
                raise ValueError(f"module id missing or duplicate: {cls.__name__}")
            self.modules[m.id] = m

    def defaults(self) -> Dict[str, Dict[str, Any]]:
        return {mid: dict(m.defaults) for mid, m in self.modules.items()}

    def bind(self, settings: Dict[str, Any], save: Callable[[], None],
             emit: Callable[[str, Any], Awaitable[None]]) -> None:
        for mid, m in self.modules.items():
            m.bind(settings["modules"][mid], save, emit)

    def get(self, mid: str) -> Module:
        if mid not in self.modules:
            raise KeyError(f"unknown module {mid!r}")
        return self.modules[mid]

    def status(self) -> Dict[str, Any]:
        return {mid: m.status() for mid, m in self.modules.items()}

    async def _each(self, hook: str, *args: Any, only_supported: bool = True) -> None:
        for mid, m in self.modules.items():
            if only_supported and not m.supported()[0]:
                continue
            try:
                await getattr(m, hook)(*args)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] %s failed", mid, hook)
                m.last_error = f"{hook} failed: {e}"

    async def start(self) -> None:
        await self._each("start")

    async def stop(self) -> None:
        await self._each("stop", only_supported=False)

    async def on_resume(self, slept_s: float) -> None:
        await self._each("on_resume", slept_s)

    async def uninstall(self) -> None:
        await self._each("uninstall", only_supported=False)
