"""Decky Loader entry point; async facade over py_modules/allycompanion."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, Optional

import decky  # type: ignore

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "py_modules"))

from allycompanion import backup, cleanup, userfs, conflicts, deckyfix, device, diagnostics, live, migrate, paths, settings, steam, updater  # noqa: E402
from allycompanion.jacksense import JackSense  # noqa: E402
from allycompanion.util import run  # noqa: E402
from allycompanion.module import Context, spawn  # noqa: E402
from allycompanion.modules import MODULES  # noqa: E402
from allycompanion.registry import Registry  # noqa: E402
from allycompanion.resume import ResumeDetector  # noqa: E402
from allycompanion.uevent import UeventMonitor  # noqa: E402


class Plugin:
    # ---------------------------------------------------------------- lifecycle
    async def _main(self):
        if not deckyfix.park_reader_at_eof():
            decky.logger.warning("Decky socket workaround not applied; stopping may take 5 s")
        self.loop = asyncio.get_running_loop()
        await asyncio.to_thread(paths.ensure_dirs)
        await asyncio.to_thread(cleanup.cancel)
        await asyncio.to_thread(updater.clear_staging)  # a zip from an update that is done or was declined
        self.registry = Registry(MODULES)
        self.settings: Dict[str, Any] = await asyncio.to_thread(settings.load, self.registry.defaults())
        if migrate.run(self.settings, self.registry.defaults()):
            self._save()
        self.uevent = UeventMonitor()
        try:
            self.uevent.start()
        except OSError as e:
            decky.logger.error("uevent monitor not started: %s", e)
        self.jack = JackSense()
        self.jack.start()
        self.registry.bind(self.settings, Context(self._save, decky.emit, self.uevent, jack=self.jack))
        self._save()  # the normalized settings
        self.update_task: Optional[asyncio.Task] = None
        self.update_lock = asyncio.Lock()
        self.resume = ResumeDetector(self.registry.on_resume)
        self.resume.start()
        spawn(self._startup())
        decky.logger.info("Ally Companion backend started (euid %s, board %s)", os.geteuid(), device.board())

    # _unload and _uninstall do not await long work: if deckyfix could not stop Decky's socket
    # loop from spinning, the event loop never runs again once the stop begins.
    async def _unload(self):
        self.resume.stop()
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()
        spawn(self.registry.stop())
        self.uevent.stop()
        self.jack.stop()
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
        self.registry.set_blocked(await asyncio.to_thread(conflicts.blocked))
        return {
            "version": decky.DECKY_PLUGIN_VERSION,
            "device": info,
            "stack": stack,
            "conflicts": await asyncio.to_thread(conflicts.active_plugins),
            "modules": await self.registry.status(),
            "update": self._update_info(),
        }

    # ---------------------------------------------------------------- modules
    # Any local process can reach these methods through Decky's socket: every argument is checked
    # by the module like a value from settings.json.
    async def _module_result(self, mid: str, error: str = "", result: Any = None) -> Dict[str, Any]:
        m = self.registry.get(mid)
        st = await m.status_async()
        if mid in self.registry.blocked:
            st.update({"state": "blocked", "blockedBy": self.registry.blocked[mid]})
        await decky.emit("module_status", st)
        err = error or m.last_error
        return {"ok": not err, "error": err, "result": result, "status": st}

    async def set_module_enabled(self, mid: str, enabled: bool) -> Dict[str, Any]:
        m = self.registry.get(mid)  # an unknown id is an error for the caller, not a module result
        try:
            self.registry.check_not_blocked(mid)
            ok, reason = m.supported()
            if not ok:
                return await self._module_result(mid, reason)
            await m.set_enabled(bool(enabled))
            return await self._module_result(mid)
        except Exception as e:  # noqa: BLE001
            return await self._module_result(mid, str(e))

    async def set_module_options(self, mid: str, options: Dict[str, Any]) -> Dict[str, Any]:
        m = self.registry.get(mid)
        try:
            self.registry.check_not_blocked(mid)
            await m.change_options(options if isinstance(options, dict) else {})
            return await self._module_result(mid)
        except Exception as e:  # noqa: BLE001
            decky.logger.warning("[%s] options failed: %s", mid, e)
            return await self._module_result(mid, str(e))

    async def module_action(self, mid: str, action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        m = self.registry.get(mid)
        try:
            self.registry.check_not_blocked(mid)
            fn = m.actions().get(action)
            if fn is None:
                raise KeyError(f"{mid} has no action {action!r}")
            result = await fn(**(args if isinstance(args, dict) else {}))
            return await self._module_result(mid, result=result)
        except Exception as e:  # noqa: BLE001
            decky.logger.warning("[%s] %s failed: %s", mid, action, e)
            return await self._module_result(mid, str(e))

    async def on_running_app_changed(self, app_id: Optional[str]) -> Dict[str, Any]:
        app = str(app_id) if app_id else None
        if app is not None and not (app.isdigit() and len(app) <= 20):
            raise ValueError(f"unexpected app id {app_id!r}")
        await self.registry.on_app_changed(app)
        await self._emit_state()  # pages show the running game's settings
        return {"appId": app}

    async def restart_steam(self) -> Dict[str, Any]:
        return await steam.restart()

    # ---------------------------------------------------------------- live values, backups, repair
    async def get_live(self) -> Dict[str, Any]:
        return await asyncio.to_thread(live.snapshot)

    async def backup_settings(self) -> Dict[str, Any]:
        audio = self.registry.modules.get("audio")
        data = backup.build(self.settings["modules"], audio.export() if audio else {}, decky.DECKY_PLUGIN_VERSION)  # type: ignore[attr-defined]
        name = await asyncio.to_thread(backup.write, data)
        decky.logger.info("settings backed up to %s", name)
        return {"name": name, "dir": backup.backup_dir()}

    async def list_backups(self) -> Dict[str, Any]:
        return {"dir": backup.backup_dir(), "backups": await asyncio.to_thread(backup.listing)}

    async def restore_backup(self, name: str) -> Dict[str, Any]:
        data = await asyncio.to_thread(backup.read, name)
        restored = await self.registry.restore(data["modules"], backup.TRANSIENT)
        audio = self.registry.modules.get("audio")
        if audio and data["audio"] and "audio" not in self.registry.blocked:
            await audio.restore(data["audio"])  # type: ignore[attr-defined]
        decky.logger.info("settings restored from %s", name)
        await self._emit_state()
        return {"restored": restored}

    async def repair_controller(self) -> Dict[str, Any]:
        """Restart InputPlumber, then send everything the controller MCU keeps again."""
        r = await asyncio.to_thread(run, ["systemctl", "restart", "inputplumber"], 30)
        if not r.ok:
            return {"ok": False, "error": (r.err or r.out).strip()[:200]}
        await asyncio.sleep(3)
        for mid in ("vibration", "lighting"):
            m = self.registry.modules.get(mid)
            if m and m.supported()[0] and mid not in self.registry.blocked:
                await m.on_resume(0.0)
        decky.logger.info("controller repaired: inputplumber restarted, settings re-sent")
        return {"ok": True, "error": ""}

    # ---------------------------------------------------------------- updates
    async def check_for_update(self, force: bool = False) -> Dict[str, Any]:
        async with self.update_lock:  # the startup check, a due check and the button never overlap
            state = dict(self.settings["update"])  # the worker thread fills a copy
            res = await asyncio.to_thread(updater.check, state, decky.DECKY_PLUGIN_VERSION, bool(force))
            self.settings["update"] = state
            self._save()
        await decky.emit("update_state", res)
        return res

    def _update_info(self) -> Dict[str, Any]:
        """Cached update state; a due check runs in the background and reports through update_state."""
        state = self.settings["update"]
        if state.get("autoCheck", True) and updater.check_due(state) and not self.update_lock.locked() \
                and not (self.update_task and not self.update_task.done()):
            self.update_task = spawn(self.check_for_update(False))
        return updater.check(state, decky.DECKY_PLUGIN_VERSION, fetch=False)

    async def prepare_update(self) -> Dict[str, Any]:
        # Asked fresh, never from the cache in settings.json (a file in a directory the user owns):
        # a planted cache entry could point at an older, validly signed release.
        latest = await asyncio.to_thread(updater.fetch_latest)
        if not latest:
            raise RuntimeError("no release published yet")
        if not updater.is_newer(str(latest.get("version")), decky.DECKY_PLUGIN_VERSION):
            raise RuntimeError(f"v{latest.get('version')} is not newer than v{decky.DECKY_PLUGIN_VERSION}")
        self.settings["update"]["latest"] = latest
        self._save()
        release = await asyncio.to_thread(updater.verify_release, latest)
        return await asyncio.to_thread(updater.download_verified, release)

    # ---------------------------------------------------------------- diagnostics
    async def get_diagnostics(self) -> Dict[str, Any]:
        d = await asyncio.to_thread(diagnostics.collect, await self.registry.status())
        d["jack"] = {"device": self.jack.path, "events": self.jack.available}
        text = diagnostics.render_text(d)
        try:  # the log directory belongs to the user
            await asyncio.to_thread(userfs.write_text, os.path.join(paths.LOG_DIR, "diagnostics.txt"), text + "\n")
        except OSError:
            pass
        return {"text": text}
