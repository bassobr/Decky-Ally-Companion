"""Decky Loader entry point; async facade over py_modules/allycompanion."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, Optional

import decky  # type: ignore

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "py_modules"))

from allycompanion import deckyfix, device, diagnostics, paths, settings, updater  # noqa: E402
from allycompanion.modules import MODULES  # noqa: E402
from allycompanion.registry import Registry  # noqa: E402
from allycompanion.resume import ResumeDetector  # noqa: E402


class Plugin:
    # ---------------------------------------------------------------- lifecycle
    async def _main(self):
        if not deckyfix.park_reader_at_eof():
            decky.logger.warning("Decky socket workaround not applied; stopping may take 5 s")
        self.loop = asyncio.get_event_loop()
        paths.ensure_dirs()
        self.registry = Registry(MODULES)
        self.settings: Dict[str, Any] = settings.load(self.registry.defaults())
        self.registry.bind(self.settings, self._save, decky.emit)
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
        decky.logger.info("Ally Companion backend unloaded")

    async def _uninstall(self):
        # Decky also calls this while replacing the plugin during an update. Modules that change
        # system state must defer their cleanup until the plugin is really gone (see Ally DSP).
        self.loop.create_task(self.registry.uninstall())

    async def _startup(self):
        try:
            await self.registry.start()
            if self.settings["update"].get("autoCheck", True):
                await self.check_for_update(False)
        except Exception as e:
            decky.logger.error("startup failed: %s", e)

    def _save(self) -> None:
        settings.save(self.settings)

    # ---------------------------------------------------------------- state
    async def get_state(self) -> Dict[str, Any]:
        info = await asyncio.to_thread(device.info)
        stack = await asyncio.to_thread(device.stack)
        return {
            "version": decky.DECKY_PLUGIN_VERSION,
            "device": info,
            "stack": stack,
            "modules": self.registry.status(),
            "update": self._update_info(),
        }

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
        d = await asyncio.to_thread(diagnostics.collect, self.registry.status())
        text = diagnostics.render_text(d)
        try:
            os.makedirs(paths.LOG_DIR, exist_ok=True)
            with open(os.path.join(paths.LOG_DIR, "diagnostics.txt"), "w", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        return {"text": text}
