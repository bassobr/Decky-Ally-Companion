"""Builds the modules, binds their settings sections and fans out lifecycle events."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Type

from . import conflicts
from .log import logger
from .module import Context, Module


class Registry:
    def __init__(self, classes: List[Type[Module]]) -> None:
        self.modules: Dict[str, Module] = {}
        for cls in classes:
            m = cls()
            if not m.id or m.id in self.modules:
                raise ValueError(f"module id missing or duplicate: {cls.__name__}")
            self.modules[m.id] = m
        self.ctx: Optional[Context] = None
        self.blocked: Dict[str, str] = {}  # module id -> plugin that drives the same hardware

    def defaults(self) -> Dict[str, Dict[str, Any]]:
        return {mid: dict(m.defaults) for mid, m in self.modules.items()}

    def bind(self, settings: Dict[str, Any], ctx: Context) -> None:
        self.ctx = ctx
        ctx.settings = settings
        for mid, m in self.modules.items():
            m.bind(settings["modules"][mid], ctx)

    def get(self, mid: str) -> Module:
        if mid not in self.modules:
            raise KeyError(f"unknown module {mid!r}")
        return self.modules[mid]

    def refresh_blocked(self) -> None:
        self.blocked = conflicts.blocked()

    def check_not_blocked(self, mid: str) -> None:
        if mid in self.blocked:
            raise RuntimeError(f"{self.blocked[mid]} is installed and drives the same hardware; "
                               f"uninstall or disable it in Decky first")

    async def status(self) -> Dict[str, Any]:
        out = {}
        for mid, m in self.modules.items():
            try:
                out[mid] = await m.status_async()
                if mid in self.blocked and out[mid]["supported"]:
                    out[mid].update({"state": "blocked", "blockedBy": self.blocked[mid],
                                     "message": f"{self.blocked[mid]} is installed and drives the same hardware"})
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] status failed", mid)
                out[mid] = {"id": mid, "title": m.title, "supported": False, "toggle": m.toggle,
                            "enabled": m.enabled, "state": "error", "message": f"status failed: {e}", "details": {}}
        return out

    async def _each(self, hook: str, *args: Any, only_supported: bool = True, skip_blocked: bool = True) -> None:
        for mid, m in self.modules.items():
            if only_supported and not m.supported()[0]:
                continue
            if skip_blocked and mid in self.blocked:
                continue
            try:
                await getattr(m, hook)(*args)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] %s failed", mid, hook)
                m.last_error = f"{hook} failed: {e}"

    async def start(self) -> None:
        self.refresh_blocked()
        await self._each("start")

    async def stop(self) -> None:
        await self._each("stop", only_supported=False, skip_blocked=False)

    async def on_resume(self, slept_s: float) -> None:
        await self._each("on_resume", slept_s)
        for m in self.modules.values():
            await m.notify()

    async def on_app_changed(self, app_id: Optional[str]) -> None:
        if self.ctx:
            self.ctx.running_app = app_id
        await self._each("on_app_changed", app_id)

    async def uninstall(self) -> None:
        await self._each("uninstall")
