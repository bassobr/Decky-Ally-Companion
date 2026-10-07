"""Builds the modules, binds their settings sections and fans out lifecycle events.

A module whose hardware is not there when the plugin starts is started as soon as it appears. On the
ROG Ally X the controller re-enumerates about 6.5 s after boot (the driver removes and re-creates
the LED rings and gamepad attributes), and Decky may start the backend in exactly that gap.
The cue is the driver's bind: hid_asus_ally creates the rings early in its probe and the interface
to the controller's MCU about 1.6 s later, at the end.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set, Type

from . import conflicts, settings as settings_mod
from .log import logger
from .module import Context, Module, spawn

LATE_SUBSYSTEMS = ("hid",)  # bind uevents after which a module may have become supported
LATE_SETTLE_S = 1.5  # the controller's other interfaces bind within a moment
LATE_CHECKS_S = (10.0, 30.0, 60.0)  # without uevents too


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
        self.started: Set[str] = set()  # modules whose start() ran
        self._late: Optional[asyncio.Task] = None
        self._late_again = False

    def defaults(self) -> Dict[str, Dict[str, Any]]:
        return {mid: dict(m.defaults) for mid, m in self.modules.items()}

    def bind(self, settings: Dict[str, Any], ctx: Context) -> None:
        self.ctx = ctx
        ctx.settings = settings
        ctx.modules = self.modules
        ctx.blocked = self.blocked
        for mid, m in self.modules.items():
            # typed against the defaults, then checked by the module (imports from predecessors too)
            section = settings_mod.merge(dict(m.defaults), settings["modules"].get(mid))
            m.normalize(section)
            settings["modules"][mid] = section
            m.bind(section, ctx)

    def get(self, mid: str) -> Module:
        if mid not in self.modules:
            raise KeyError(f"unknown module {mid!r}")
        return self.modules[mid]

    def refresh_blocked(self) -> None:
        self.set_blocked(conflicts.blocked())

    def set_blocked(self, blocked: Dict[str, str]) -> None:
        """On the event loop only: modules read this dict there."""
        self.blocked.clear()  # the context holds the same dict
        self.blocked.update(blocked)

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

    @staticmethod
    async def _hook(mid: str, m: Module, hook: str, *args: Any) -> None:
        try:
            await getattr(m, hook)(*args)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] %s failed", mid, hook)
            m.last_error = f"{hook} failed: {e}"

    async def _each(self, hook: str, *args: Any, only_supported: bool = True, skip_blocked: bool = True,
                    concurrent: bool = False) -> None:
        targets = [(mid, m) for mid, m in self.modules.items()
                   if not (only_supported and not m.supported()[0]) and not (skip_blocked and mid in self.blocked)]
        if concurrent:  # one module waiting (the fan settles for seconds) must not hold up the others
            await asyncio.gather(*(self._hook(mid, m, hook, *args) for mid, m in targets))
            return
        for mid, m in targets:
            await self._hook(mid, m, hook, *args)

    async def start(self) -> None:
        self.refresh_blocked()
        for mid, m in self.modules.items():
            if not m.supported()[0]:
                continue
            try:
                await m.prepare(self.blocked.get(mid))
            except Exception:  # noqa: BLE001
                logger.exception("[%s] prepare failed", mid)
        self.started = {mid for mid, m in self.modules.items() if mid not in self.blocked and m.supported()[0]}
        await self._each("start")
        if self.ctx and self.ctx.uevent:
            for subsystem in LATE_SUBSYSTEMS:
                self.ctx.uevent.subscribe(subsystem, self._on_hardware)
        spawn(self._late_checks())

    def unload(self) -> None:
        for mid, m in self.modules.items():
            try:
                m.unload()
            except Exception:  # noqa: BLE001
                logger.exception("[%s] unload failed", mid)

    # ------------------------------------------------------------- hardware that appears later
    async def _on_hardware(self, event: Dict[str, str]) -> None:
        if event.get("ACTION") != "bind":
            return
        self._late_again = True
        if self._late is None or self._late.done():
            self._late = spawn(self._late_after_events())

    async def _late_after_events(self) -> None:
        while self._late_again:  # an event during a check gets a check of its own (the driver's bind)
            self._late_again = False
            await self.start_late(LATE_SETTLE_S)

    async def _late_checks(self) -> None:
        waited = 0.0
        for at in LATE_CHECKS_S:
            await asyncio.sleep(at - waited)
            waited = at
            await self.start_late()

    async def start_late(self, delay: float = 0.0) -> List[str]:
        """Start the modules that were not supported at the start but are now; returns their ids."""
        if delay:
            await asyncio.sleep(delay)
        late = []
        for mid, m in self.modules.items():
            if mid in self.started or mid in self.blocked or not m.supported()[0]:
                continue
            self.started.add(mid)
            logger.info("[%s] hardware appeared after the plugin started: starting now", mid)
            try:
                await m.prepare(None)
                await m.start()
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] late start failed", mid)
                m.last_error = f"start failed: {e}"
            late.append(mid)
            await m.notify()
        return late

    async def on_resume(self, slept_s: float) -> None:
        await self._each("on_resume", slept_s, concurrent=True)
        for m in self.modules.values():
            await m.notify()

    async def on_app_changed(self, app_id: Optional[str]) -> None:
        if self.ctx:
            self.ctx.running_app = app_id
        await self._each("on_app_changed", app_id, concurrent=True)

    async def uninstall(self) -> None:
        # Not filtered by supported(): when the cleanup runs, the plugin's own files (shim, LV2
        # bundle) that some supported() checks look for are already gone.
        await self._each("uninstall", only_supported=False, skip_blocked=False)

    async def restore(self, sections: Dict[str, Any], keep: Optional[Dict[str, Any]] = None) -> List[str]:
        """Replace module sections (from a backup) and bring the hardware in line; returns the ids.
        `keep` names per module the runtime keys that stay as they are (a full charge in progress,
        the battery history, the performance profile to restore after a game)."""
        done = []
        for mid, data in sections.items():
            m = self.modules.get(mid)
            if m is None or not isinstance(data, dict):
                continue
            was_enabled = m.enabled
            new = settings_mod.merge(dict(m.defaults), data)
            m.normalize(new)  # a backup is a file the user can edit
            for k in (keep or {}).get(mid, ()):
                if k in m.cfg:
                    new[k] = m.cfg[k]
            m.cfg.clear()
            m.cfg.update(new)  # same dict object as in the settings tree
            done.append(mid)
            if not m.supported()[0] or mid in self.blocked:
                continue
            try:
                await m.stop()
                if m.toggle and was_enabled and not m.enabled:
                    await m.revert()
                self.started.add(mid)
                await m.start()
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] restore failed", mid)
                m.last_error = f"restore failed: {e}"
        if self.ctx:
            self.ctx.save()
        return done
