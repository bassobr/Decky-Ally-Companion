"""Base class of every feature module.

The toggle semantics (enabled flag, apply/revert, is_applied, status states) are adapted from
the Fix class of Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT). A module owns one
settings section, says whether the hardware supports it, applies and reverts its changes and
gets called after resume. Modules never block the event loop for long; slow work goes through
asyncio.to_thread.

Status states: applied, not_applied, error, stale, restart_pending, not_supported, info (a
module without an enabled flag), blocked (another plugin drives the same hardware; set by the
registry).
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

from .log import logger


class Context:
    """What the registry hands to every module."""

    def __init__(self, save: Callable[[], None], emit: Callable[[str, Any], Awaitable[None]],
                 uevent: Any = None, settings: Optional[Dict[str, Any]] = None, jack: Any = None) -> None:
        self.save = save
        self.emit = emit
        self.uevent = uevent
        self.jack = jack  # jacksense.JackSense: headphone jack events
        self.settings = settings or {}  # the whole settings tree, read-only for modules
        self.running_app: Optional[str] = None
        self.modules: Dict[str, "Module"] = {}  # the other modules, for the profiles module
        self.blocked: Dict[str, str] = {}  # module id -> plugin that drives the same hardware


_background: "Set[asyncio.Task]" = set()


def spawn(coro: Awaitable[Any]) -> "asyncio.Task":
    """create_task with a strong reference until the task ends (the loop only keeps weak ones)."""
    task = asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


async def cancel_task(task: "Optional[asyncio.Task]") -> None:
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass


class Module:
    id: str = ""
    title: str = ""
    defaults: Dict[str, Any] = {}
    # True: the module has an "enabled" switch; start() applies and uninstall() reverts.
    toggle: bool = False

    def __init__(self) -> None:
        self.cfg: Dict[str, Any] = {}
        self.ctx: Optional[Context] = None
        self.last_error: str = ""
        self._lock_obj: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        """Serializes hardware changes of this module; created on first use, inside the loop."""
        if self._lock_obj is None:
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    def bind(self, cfg: Dict[str, Any], ctx: Context) -> None:
        self.cfg, self.ctx = cfg, ctx

    def normalize(self, cfg: Dict[str, Any]) -> None:
        """Check a settings section in place (values come from a file the user owns, or a backup):
        ranges, enums and nested structures beyond the types settings.merge already enforces."""

    # ------------------------------------------------------------- settings
    def save(self) -> None:
        if self.ctx:
            self.ctx.save()

    def update_cfg(self, values: Dict[str, Any]) -> None:
        self.cfg.update(values)
        self.save()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", False))

    # ------------------------------------------------------------- hooks for subclasses
    def supported(self) -> Tuple[bool, str]:
        return True, ""

    def is_applied(self) -> Optional[bool]:
        return None

    async def apply(self) -> None:
        """Bring the system in line with the settings (enabled)."""

    async def revert(self) -> None:
        """Undo everything apply() changed."""

    def details(self) -> Dict[str, Any]:
        """Module-specific values for the UI; runs in a worker thread."""
        return {}

    def set_options(self, opts: Dict[str, Any]) -> bool:
        """Validate and store options; True when something changed that apply() must push."""
        return False

    def actions(self) -> Dict[str, Callable[..., Awaitable[Any]]]:
        """Extra calls the UI may make: name -> coroutine function taking keyword arguments."""
        return {}

    async def prepare(self, blocked_by: Optional[str]) -> None:
        """Plugin start, before start() and also while another plugin blocks the module."""

    async def start(self) -> None:
        """Plugin start: re-apply what the settings say."""
        await self.reapply_if_enabled()

    async def stop(self) -> None:
        """Plugin unload: cancel background work; changes stay applied."""

    async def on_resume(self, slept_s: float) -> None:
        """After suspend; the controller MCU loses most of its settings there."""

    async def on_app_changed(self, app_id: Optional[str]) -> None:
        """The running game changed (None: back in the library)."""

    async def uninstall(self) -> None:
        """Plugin removed: revert everything this module changed outside the plugin directory."""
        if self.toggle and self.enabled:
            await self.revert()

    # ------------------------------------------------------------- operations
    async def set_enabled(self, on: bool) -> None:
        self.update_cfg({"enabled": bool(on)})
        self.last_error = ""
        try:
            await (self.apply() if on else self.revert())
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] %s failed", self.id, "apply" if on else "revert")
            self.last_error = str(e)

    async def change_options(self, opts: Dict[str, Any]) -> None:
        if self.set_options(opts or {}) and (self.enabled or not self.toggle):
            await self.reapply_if_enabled(force=True)

    async def reapply_if_enabled(self, force: bool = False) -> None:
        if not (self.enabled or (force and not self.toggle)) or not self.supported()[0]:
            return
        try:
            await self.apply()
            self.last_error = ""
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] apply failed", self.id)
            self.last_error = str(e)

    async def notify(self) -> None:
        if self.ctx:
            try:
                await self.ctx.emit("module_status", await self.status_async())
            except Exception:  # noqa: BLE001
                logger.exception("[%s] notify failed", self.id)

    def _state(self) -> Tuple[str, str]:
        """(state, message) before module-specific refinement."""
        if self.last_error:
            return "error", self.last_error
        if not self.toggle:
            return "info", ""
        try:
            applied = self.is_applied()
        except Exception as e:  # noqa: BLE001
            return "error", f"status check failed: {e}"
        return ("applied" if applied else "not_applied"), ""

    def refine(self, state: str, message: str, details: Dict[str, Any]) -> Tuple[str, str]:
        """Subclasses turn applied/not_applied into stale, restart_pending, ..."""
        return state, message

    def _status_parts(self) -> Tuple[str, str, Dict[str, Any]]:
        try:
            details = self.details()
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] details failed", self.id)
            details = {"error": str(e)}
        state, message = self._state()
        state, message = self.refine(state, message, details)
        return state, message, details

    async def status_async(self) -> Dict[str, Any]:
        ok, reason = self.supported()
        out: Dict[str, Any] = {"id": self.id, "title": self.title, "supported": ok, "toggle": self.toggle,
                               "enabled": self.enabled, "state": "not_supported", "message": reason,
                               "details": {}}
        if not ok:
            return out
        # details() and is_applied() read files and run systemctl/busctl: off the event loop
        state, message, details = await asyncio.to_thread(self._status_parts)
        out.update({"state": state, "message": message, "details": details})
        return out
