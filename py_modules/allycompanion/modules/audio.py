"""Speaker DSP: the Dolby tuning of the ROG Ally as a PipeWire filter chain (from Ally DSP).

Everything that writes (download, venv, conversion, presets, the systemd user unit) runs in the
worker `allydsp.worker` as the Decky user, exactly as Ally DSP ran it. This module reads state,
watches the headphone jack (stopping and starting the unit through `systemctl --user`), keeps the
audio settings (allydsp's settings.json, owned by the user) and switches presets per game.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from allydsp import asus_fetch, convert, dsp_runtime, hardware
from allydsp import paths as dsp_paths
from allydsp.util import makedirs_user
from allydsp import settings as dsp_settings
from allydsp.constants import INPUT_NODE, PROFILES, VOICING_LABELS, VOICINGS
from allydsp.jackwatch import JackWatcher
from allydsp.setup_flow import STEPS

from .. import paths
from ..log import logger
from ..module import Module, cancel_task
from ..util import _drop_kwargs, user_env

LEGACY_SETTINGS = os.path.join(paths.HOME, "homebrew", "settings", "Ally DSP", "settings.json")
LEGACY_PLUGIN = "Ally DSP"
IMPORTED_KEYS = ("enabled", "global", "perApp", "extras")


class WorkerError(RuntimeError):
    def __init__(self, message: str, cancelled: bool = False):
        super().__init__(message)
        self.cancelled = cancelled


def worker_env() -> Dict[str, str]:
    return user_env({
        "PYTHONPATH": os.path.join(paths.PLUGIN_DIR, "py_modules"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "DECKY_USER_HOME": paths.HOME,
        "DECKY_USER": paths.USER,
        "ALLYCOMPANION_PLUGIN_DIR": paths.PLUGIN_DIR,
        "DECKY_PLUGIN_RUNTIME_DIR": paths.RUNTIME_DIR,
        "DECKY_PLUGIN_LOG_DIR": paths.LOG_DIR,
    })


class Worker:
    """One `allydsp.worker` call: JSON lines in, progress callback, result or WorkerError."""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def run(self, args: List[str], progress: Optional[Callable[[Dict[str, Any]], None]] = None,
            timeout: float = 3600) -> Any:
        cmd = [dsp_paths.SYSTEM_PYTHON, "-m", "allydsp.worker", *args]
        with self._lock:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                         env=worker_env(), cwd=paths.PLUGIN_DIR, **_drop_kwargs())  # type: ignore[arg-type]
        proc = self.proc
        result: Any = None
        error: Optional[WorkerError] = None
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                kind = msg.pop("type", None)
                if kind == "progress" and progress:
                    progress(msg)
                elif kind == "result":
                    result = msg.get("data")
                elif kind == "error":
                    error = WorkerError(str(msg.get("error")), bool(msg.get("cancelled")))
            proc.wait()
        finally:
            timer.cancel()
            self.proc = None
        if error:
            raise error
        if proc.returncode != 0:
            err = (proc.stderr.read() if proc.stderr else "").strip().splitlines()[-3:]
            raise WorkerError(f"worker {args[0]} failed (rc={proc.returncode}): {' | '.join(err)}")
        return result

    def terminate(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            p.terminate()


class Audio(Module):
    id = "audio"
    title = "Speaker DSP"
    toggle = True
    defaults: Dict[str, Any] = {}

    def __init__(self) -> None:
        super().__init__()
        self.worker = Worker()
        self.jack = JackWatcher(on_change=self._on_jack)
        self.running_app: Optional[str] = None
        self.setup_task: Optional[asyncio.Task] = None
        self.setup_last: Optional[Dict[str, Any]] = None
        self.convert_task: Optional[asyncio.Task] = None
        self.convert_last: Optional[Dict[str, Any]] = None
        # flags, not task.done(): the final status is sent from inside the task
        self.setup_running = False
        self.converting = False
        self._codec: Optional[Dict[str, Any]] = None
        self._codec_read = False
        self._lv2: Optional[Dict[str, Any]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------- settings
    def dsp(self) -> Dict[str, Any]:
        return dsp_settings.load()

    def save_dsp(self, s: Dict[str, Any]) -> None:
        dsp_settings.save_keeping(s, "setup")  # the worker writes "setup"

    @property
    def enabled(self) -> bool:
        return bool(self.dsp().get("enabled"))

    def setup_done(self) -> bool:
        return bool(self.dsp()["setup"].get("done"))

    def busy(self) -> bool:
        return self.setup_running or self.converting

    def should_run(self) -> bool:
        s = self.dsp()
        return bool(s.get("enabled") and s["setup"].get("done"))

    def codec(self) -> Optional[Dict[str, Any]]:
        if not self._codec_read:
            self._codec = hardware.codec_info()
            self._codec_read = True
        return self._codec

    # ------------------------------------------------------------- module interface
    def supported(self) -> Tuple[bool, str]:
        c = self.codec()
        if not c:
            return False, "no Realtek HDA codec found"
        if not os.path.isdir(os.path.join(dsp_paths.LV2_DIR, "lsp-plugins.lv2")):
            return False, "LV2 plugins missing from the plugin (bin/lv2)"
        if not convert.converter_ok():
            return False, "converter missing from the plugin (defaults/converter)"
        return True, ""

    def is_applied(self) -> bool:
        return self.setup_done() and (dsp_runtime.is_active() or bool(self.jack.paused))

    def refine(self, state: str, message: str, details: Dict[str, Any]) -> Tuple[str, str]:
        if state == "error":
            return state, message
        if self.setup_running:
            return "info", (self.setup_last or {}).get("message", "Setting up")
        if not details.get("setup", {}).get("done"):
            return "not_applied", "Setup needed"
        if details.get("dsp", {}).get("paused"):
            return "applied", "Paused while headphones are in use"
        return state, message

    def details(self) -> Dict[str, Any]:
        s = self.dsp()
        dump = hardware.pw_dump()
        if self._lv2 is None:
            self._lv2 = hardware.lv2_check()
        setup = dict(s["setup"])
        setup.update({"xmlPresent": bool(asus_fetch.current_xml()), "venvOk": convert.venv_ok(),
                      "presets": convert.list_presets(), "inProgress": self.setup_running,
                      "last": self.setup_last, "converting": self.converting,
                      "convertLast": self.convert_last})
        route = hardware.output_route(dump)
        return {
            "setup": setup,
            "enabledSetting": bool(s.get("enabled")),
            "global": s["global"], "perApp": s.get("perApp") or {}, "extras": s["extras"],
            "dsp": {"active": dsp_runtime.is_active(), "verified": hardware.filter_node_present(dump, INPUT_NODE),
                    "activePreset": dsp_runtime.active_meta(), "paused": bool(self.jack.paused)},
            "headphones": hardware.headphones_active(route),
            "codec": self.codec(), "sink": hardware.find_speaker_sink(dump),
            "lv2": self._lv2,
            "runningApp": self.running_app, "resolved": dsp_settings.resolve(s, self.running_app),
            "profiles": [{"id": p, "label": label} for p, label in PROFILES],
            "voicings": [{"id": v, "label": VOICING_LABELS[v]} for v in VOICINGS],
            "steps": STEPS,
        }

    async def prepare(self, blocked_by: Optional[str]) -> None:
        """Runs also while Ally DSP is still installed: keep its settings and data in reach."""
        makedirs_user(dsp_paths.RUNTIME_DIR)  # the worker runs as the user and writes below it
        if blocked_by == LEGACY_PLUGIN or not os.path.exists(dsp_paths.SETTINGS_FILE):
            self._import_legacy_settings()
        if os.path.isdir(dsp_paths.LEGACY_RUNTIME_DIR) and (not asus_fetch.current_xml() or not convert.venv_ok()):
            try:
                res = await asyncio.to_thread(self.worker.run, ["import-legacy"])
                if res and res.get("imported"):
                    logger.info("[audio] imported from Ally DSP: %s", ", ".join(res["imported"]))
            except WorkerError as e:
                logger.warning("[audio] import from Ally DSP failed: %s", e)

    def _import_legacy_settings(self) -> None:
        try:
            with open(LEGACY_SETTINGS, "r", encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            return
        s = self.dsp()
        for k in IMPORTED_KEYS:
            if k in old:
                s[k] = old[k]
        self.save_dsp(s)
        logger.info("[audio] settings taken from Ally DSP")

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self.jack.start(self.should_run)
        if self.setup_done():
            await self._reconcile()
        elif asus_fetch.current_xml():
            await self.run_setup()  # tuning already here (imported): convert without asking

    async def stop(self) -> None:
        self.jack.cancel()
        self.worker.terminate()
        await cancel_task(self.setup_task)
        await cancel_task(self.convert_task)

    async def uninstall(self) -> None:
        try:
            await asyncio.to_thread(self.worker.run, ["remove"])
        except WorkerError as e:
            logger.warning("[audio] removing the unit failed: %s", e)
        shutil.rmtree(dsp_paths.RUNTIME_DIR, ignore_errors=True)

    async def on_app_changed(self, app_id: Optional[str]) -> None:
        if app_id != self.running_app:
            self.running_app = app_id
            if self.should_run():
                await self._apply_current()

    async def set_enabled(self, on: bool) -> None:
        s = self.dsp()
        s["enabled"] = bool(on)
        self.save_dsp(s)
        self.last_error = ""
        try:
            if on:
                await asyncio.to_thread(self.worker.run, ["enable"])
                await self._apply_current(force_restart=True)
            else:
                await asyncio.to_thread(self.worker.run, ["disable"])
        except Exception as e:  # noqa: BLE001
            logger.exception("[audio] switching %s failed", "on" if on else "off")
            self.last_error = str(e)

    def actions(self):
        return {"run_setup": self.run_setup, "cancel_setup": self.cancel_setup, "set_global": self.set_global,
                "set_per_app": self.set_per_app, "set_extras": self.set_extras}

    # ------------------------------------------------------------- presets
    async def _reconcile(self) -> None:
        """Bring unit and active preset back after an update or lost data."""
        have_presets = any(v for p in convert.list_presets().values() for v in p.values())
        if not have_presets or not asus_fetch.current_xml() or not await asyncio.to_thread(convert.venv_ok):
            logger.warning("[audio] setup data incomplete, running setup again")
            await self.run_setup()
            return
        if self.dsp().get("enabled"):
            await self._apply_current(force_restart=not dsp_runtime.unit_installed())

    async def _apply_current(self, force_restart: bool = False) -> None:
        """Apply the resolved preset; restart the unit only when it changes."""
        async with self._lock:
            s = self.dsp()
            res = dsp_settings.resolve(s, self.running_app)
            if not convert.preset_available(res["profile"], res["voicing"]):
                return
            pregain = dsp_settings.clamp_pregain(s["extras"].get("preGainDb", 0))
            active = dsp_runtime.active_meta() or {}
            unchanged = (active.get("profile") == res["profile"] and active.get("voicing") == res["voicing"]
                         and abs(float(active.get("preGainDb", 0) or 0) - pregain) < 1e-6)
            want_running = self.should_run() and not self.jack.paused
            if unchanged and not force_restart and dsp_runtime.unit_installed():
                if want_running and not await asyncio.to_thread(dsp_runtime.is_active):
                    await asyncio.to_thread(self.worker.run, ["start"])
                return
            args = ["apply", res["profile"], res["voicing"], "--pregain", str(pregain)]
            if not want_running:
                args.append("--no-start")
            await asyncio.to_thread(self.worker.run, args)
            if not want_running and await asyncio.to_thread(dsp_runtime.is_active):
                await asyncio.to_thread(dsp_runtime.stop)
            logger.info("[audio] preset %s/%s (%s)", res["profile"], res["voicing"], res["source"])
        await self.notify()

    async def set_global(self, profile: str, voicing: str) -> None:
        if not (dsp_settings.valid_profile(profile) and dsp_settings.valid_voicing(voicing)):
            raise ValueError("invalid profile or voicing")
        s = self.dsp()
        s["global"] = {"profile": profile, "voicing": voicing}
        self.save_dsp(s)
        if self.should_run():
            await self._apply_current()

    async def set_per_app(self, appId: str, entry: Optional[Dict[str, Any]] = None) -> None:  # noqa: N803
        app_id = str(appId)
        s = self.dsp()
        per = s.setdefault("perApp", {})
        if entry is None:
            per.pop(app_id, None)
        else:
            if not (dsp_settings.valid_profile(entry.get("profile")) and dsp_settings.valid_voicing(entry.get("voicing"))):
                raise ValueError("invalid profile or voicing")
            per[app_id] = {"profile": entry["profile"], "voicing": entry["voicing"],
                           "enabled": bool(entry.get("enabled", True)), "name": str(entry.get("name", ""))[:80]}
        self.save_dsp(s)
        if self.running_app == app_id and self.should_run():
            await self._apply_current()

    async def set_extras(self, extras: Dict[str, Any]) -> None:
        s = self.dsp()
        old = dict(s["extras"])
        new = dict(old)
        for k in ("autogain", "dialog", "regulator", "virtualBass"):
            if k in extras:
                new[k] = bool(extras[k])
        if "preGainDb" in extras:
            new["preGainDb"] = dsp_settings.clamp_pregain(extras["preGainDb"])
        s["extras"] = new
        self.save_dsp(s)
        if self.setup_running:
            return  # applied when the setup finishes
        if dsp_settings.extras_signature(new) != dsp_settings.extras_signature(old):
            self._start_reconvert()
        elif abs(float(new.get("preGainDb", 0)) - float(old.get("preGainDb", 0))) > 1e-6 and self.should_run():
            await self._apply_current()

    # ------------------------------------------------------------- setup and conversion
    def _emit_threadsafe(self, payload: Dict[str, Any]) -> None:
        if self._loop and self.ctx:
            self._loop.call_soon_threadsafe(lambda: self._loop.create_task(self.ctx.emit("audio_progress", payload)))  # type: ignore[union-attr]

    async def run_setup(self, force: bool = False, allowUnsupported: bool = False) -> Dict[str, Any]:  # noqa: N803
        if self.busy():
            return {"started": False, "reason": "already running"}
        self._loop = asyncio.get_event_loop()
        self.setup_last = None

        def progress(ev: Dict[str, Any]) -> None:
            self.setup_last = ev
            self._emit_threadsafe({"kind": "setup", **ev})

        args = ["setup"] + (["--force"] if force else []) + (["--allow-unsupported"] if allowUnsupported else [])

        async def runner() -> None:
            total = len(STEPS)
            try:
                await asyncio.to_thread(self.worker.run, args, progress)
                ev = {"step": "finished", "status": "done", "message": "Setup complete", "percent": 100, "index": total, "total": total}
                self._lv2 = None
            except WorkerError as e:
                last = self.setup_last or {}
                ev = {"step": "finished" if e.cancelled else last.get("step", "hardware"),
                      "status": "cancelled" if e.cancelled else "error", "message": str(e),
                      "percent": last.get("percent", 0), "index": last.get("index", 0), "total": total}
                if not e.cancelled:
                    logger.error("[audio] setup failed: %s", e)
            self.setup_running = False
            self.setup_last = ev
            self._emit_threadsafe({"kind": "setup", **ev})
            if ev["status"] == "done":
                s = self.dsp()
                if dsp_settings.extras_signature(s["extras"]) != s["setup"].get("extrasSignature"):
                    self._start_reconvert()
                elif self.should_run():
                    await self._apply_current(force_restart=True)
            await self.notify()

        self.setup_running = True
        self.setup_task = asyncio.get_event_loop().create_task(runner())
        return {"started": True}

    async def cancel_setup(self) -> None:
        self.worker.terminate()

    def _start_reconvert(self) -> None:
        if self.converting:
            return
        self._loop = asyncio.get_event_loop()

        def progress(ev: Dict[str, Any]) -> None:
            self.convert_last = {"percent": ev.get("percent", 0), "message": ev.get("message", ""), "status": "running"}
            self._emit_threadsafe({"kind": "convert", **self.convert_last})

        async def runner() -> None:
            try:
                while True:  # extras may change again while a conversion runs
                    sig = dsp_settings.extras_signature(self.dsp()["extras"])
                    await asyncio.to_thread(self.worker.run, ["convert"], progress)
                    if dsp_settings.extras_signature(self.dsp()["extras"]) == sig:
                        break
                self.convert_last = {"percent": 100, "message": "Presets regenerated", "status": "done"}
                self.converting = False
                if self.should_run():
                    await self._apply_current(force_restart=True)
            except Exception as e:  # noqa: BLE001
                logger.error("[audio] reconversion failed: %s", e)
                self.convert_last = {"percent": 0, "message": str(e), "status": "error"}
            self.converting = False
            self._emit_threadsafe({"kind": "convert", **self.convert_last})
            await self.notify()

        self.converting = True
        self.convert_task = asyncio.get_event_loop().create_task(runner())

    async def _on_jack(self, state: Dict[str, Any]) -> None:
        await self.notify()
