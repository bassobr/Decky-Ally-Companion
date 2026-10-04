"""Base class of every feature module.

Adapted from the Fix class of Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT). A module
owns one settings section, says whether the hardware supports it, applies and reverts its
changes, and gets called after resume. Modules never block the event loop for long; slow
work goes through asyncio.to_thread.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from .log import logger


class Module:
    id: str = ""
    title: str = ""
    defaults: Dict[str, Any] = {}

    def __init__(self) -> None:
        self.cfg: Dict[str, Any] = {}
        self.last_error: str = ""
        self._save: Optional[Callable[[], None]] = None
        self._emit: Optional[Callable[[str, Any], Awaitable[None]]] = None

    def bind(self, cfg: Dict[str, Any], save: Callable[[], None], emit: Callable[[str, Any], Awaitable[None]]) -> None:
        self.cfg, self._save, self._emit = cfg, save, emit

    def save(self) -> None:
        if self._save:
            self._save()

    async def emit_status(self) -> None:
        if self._emit:
            await self._emit("module_status", self.status())

    # ------------------------------------------------------------- hooks for subclasses
    def supported(self) -> Tuple[bool, str]:
        return True, ""

    def state(self) -> Dict[str, Any]:
        """Module-specific values for the UI."""
        return {}

    async def start(self) -> None:
        """Plugin start: re-apply what the settings say."""

    async def stop(self) -> None:
        """Plugin unload: cancel background work; changes stay applied."""

    async def on_resume(self, slept_s: float) -> None:
        """After suspend; the controller MCU loses most of its settings there."""

    async def uninstall(self) -> None:
        """Plugin removed: revert everything this module changed outside the plugin directory."""

    # ------------------------------------------------------------- helpers
    def status(self) -> Dict[str, Any]:
        ok, reason = self.supported()
        out: Dict[str, Any] = {"id": self.id, "title": self.title, "supported": ok, "reason": reason,
                               "error": self.last_error or None, "state": {}}
        if ok:
            try:
                out["state"] = self.state()
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] state failed", self.id)
                out["error"] = f"state failed: {e}"
        return out
