"""Decky Loader entry point; async facade over py_modules/allycompanion."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, Optional

import decky  # type: ignore

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "py_modules"))

from allycompanion import cleanup, conflicts, deckyfix, device, diagnostics, migrate, paths, settings, steam, updater  # noqa: E402
from allycompanion.module import Context  # noqa: E402
from allycompanion.modules import MODULES  # noqa: E402
from allycompanion.registry import Registry  # noqa: E402
from allycompanion.resume import ResumeDetector  # noqa: E402
from allycompanion.uevent import UeventMonitor  # noqa: E402


class Plugin:
    # ---------------------------------------------------------------- lifecycle
    async def _main(self):
        if not deckyfix.park_reader_at_eof():
            decky.logger.warning("Decky socket workaround not applied; stopping may take 5 s")
        self.loop = asyncio.get_event_loop()
        paths.ensure_dirs()
        await asyncio.to_thread(cleanup.cancel)
        self.registry = Registry(MODULES)
        self.settings: Dict[str, Any] = settings.load(self.registry.defaults())
        if migrate.run(self.settings, self.registry.defaults()):
            self._save()
        self.uevent = UeventMonitor()
        try:
            self.uevent.start()
        except OSError as e:
            decky.logger.error("uevent monitor not started: %s", e)
        self.registry.bind(self.settings, Context(self._save, decky.emit, self.uevent))
        self.update_task: Optional[asyncio.Task] = None
        self.resume = ResumeDetector(self.registry.on_resume)
        self.resume.start()
        self.loop.create_task(self._startup())
        decky.logger.info("Ally Companion backend started (euid %s, board %s)", os.geteuid(), device.board())

    # _unload and _uninstall do not await long work: if deckyfix could not stop Decky's socket
    # loop from spinning, the event loop never runs again once the stop begins.
    async def _unload(self):
        self.resume.stop()
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()
        self.loop.create_task(self.registry.stop())
        self.uevent.stop()
        decky.logger.info("Ally Companion backend unloaded")

    async def _uninstall(self):
        # Decky also calls this while replacing the plugin during an update; the cleanup runs a
        # minute later and only if the plugin is really gone (cleanup.py).
        if cleanup.schedule():
            decky.logger.info("uninstall: modules are reverted in %ss unless the plugin comes back", cleanup.DELAY_S)

    async def _startup(self):
        try:
            await self.registry.start()
            await self._emit_state()
            if self.settings["update"].get("autoCheck", True):
                await self.check_for_update(False)
        except Exception as e:
            decky.logger.error("startup failed: %s", e)

    def _save(self) -> None:
        settings.save(self.settings)

    async def _emit_state(self) -> None:
        await decky.emit("modules", await self.registry.status())

    # ---------------------------------------------------------------- state
    async def get_state(self) -> Dict[str, Any]:
        info = await asyncio.to_thread(device.info)
        stack = await asyncio.to_thread(device.stack)
        self.registry.refresh_blocked()
        return {
            "version": decky.DECKY_PLUGIN_VERSION,
            "device": info,
            "stack": stack,
            "conflicts": conflicts.active_plugins(),
            "modules": await self.registry.status(),
            "update": self._update_info(),
        }

    # ---------------------------------------------------------------- modules
    async def _module_result(self, mid: str, error: str = "", result: Any = None) -> Dict[str, Any]:
        m = self.registry.get(mid)
        st = await m.status_async()
        if mid in self.registry.blocked:
            st.update({"state": "blocked", "blockedBy": self.registry.blocked[mid]})
        await decky.emit("module_status", st)
        err = error or m.last_error
        return {"ok": not err, "error": err, "result": result, "status": st}

    async def set_module_enabled(self, mid: str, enabled: bool) -> Dict[str, Any]:
        try:
            self.registry.check_not_blocked(mid)
            m = self.registry.get(mid)
            ok, reason = m.supported()
            if not ok:
                return await self._module_result(mid, reason)
            await m.set_enabled(bool(enabled))
            return await self._module_result(mid)
        except Exception as e:  # noqa: BLE001
            return await self._module_result(mid, str(e))

    async def set_module_options(self, mid: str, options: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.registry.check_not_blocked(mid)
            await self.registry.get(mid).change_options(options or {})
            return await self._module_result(mid)
        except Exception as e:  # noqa: BLE001
            decky.logger.warning("[%s] options failed: %s", mid, e)
            return await self._module_result(mid, str(e))

    async def module_action(self, mid: str, action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            self.registry.check_not_blocked(mid)
            fn = self.registry.get(mid).actions().get(action)
            if fn is None:
                raise KeyError(f"{mid} has no action {action!r}")
            result = await fn(**(args or {}))
            return await self._module_result(mid, result=result)
        except Exception as e:  # noqa: BLE001
            decky.logger.warning("[%s] %s failed: %s", mid, action, e)
            return await self._module_result(mid, str(e))

    async def on_running_app_changed(self, app_id: Optional[str]) -> Dict[str, Any]:
        app = str(app_id) if app_id else None
        await self.registry.on_app_changed(app)
        return {"appId": app}

    async def restart_steam(self) -> Dict[str, Any]:
        return await steam.restart()

    # ---------------------------------------------------------------- updates
    async def check_for_update(self, force: bool = False) -> Dict[str, Any]:
        state = dict(self.settings["update"])  # the worker thread fills a copy
        res = await asyncio.to_thread(updater.check, state, decky.DECKY_PLUGIN_VERSION, bool(force))
        self.settings["update"] = state
        self._save()
        await decky.emit("update_state", res)
        return res

    def _update_info(self) -> Dict[str, Any]:
        """Cached update state; a due check runs in the background and reports through update_state."""
        state = self.settings["update"]
        if state.get("autoCheck", True) and updater.check_due(state) \
                and not (self.update_task and not self.update_task.done()):
            self.update_task = self.loop.create_task(self.check_for_update(False))
        return updater.check(state, decky.DECKY_PLUGIN_VERSION, fetch=False)

    async def prepare_update(self) -> Dict[str, Any]:
        latest = self.settings["update"].get("latest")
        if not latest:
            latest = await asyncio.to_thread(updater.fetch_latest)
            if not latest:
                raise RuntimeError("no release published yet")
            self.settings["update"]["latest"] = latest
            self._save()
        return await asyncio.to_thread(updater.verify_release, latest)

    # ---------------------------------------------------------------- diagnostics
    async def get_diagnostics(self) -> Dict[str, Any]:
        d = await asyncio.to_thread(diagnostics.collect, await self.registry.status())
        text = diagnostics.render_text(d)
        try:
            os.makedirs(paths.LOG_DIR, exist_ok=True)
            with open(os.path.join(paths.LOG_DIR, "diagnostics.txt"), "w", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        return {"text": text}
