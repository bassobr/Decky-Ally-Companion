"""Deferred uninstall.

Decky calls `_uninstall` also while it replaces the plugin during an update, and kills the backend
seconds later. So `_uninstall` only copies this package to the data directory and starts a transient
systemd timer; a minute later `cli cleanup` reverts every module, but only if plugin.json is still
gone. A starting backend cancels the timer.
"""
from __future__ import annotations

import os
import shutil
from typing import List

from . import paths
from .log import logger
from .util import run

UNIT = "ally-companion-cleanup"
PACKAGES = ("allycompanion", "allydsp")
DELAY_S = 60


def copy_dir() -> str:
    return os.path.join(paths.RUNTIME_DIR, "cleanup")


def schedule() -> bool:
    py_modules = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shutil.rmtree(copy_dir(), ignore_errors=True)
    for pkg in PACKAGES:  # the plugin directory is gone when the cleanup runs
        shutil.copytree(os.path.join(py_modules, pkg), os.path.join(copy_dir(), pkg),
                        ignore=shutil.ignore_patterns("__pycache__"))
    env: List[str] = []
    for k, v in (("DECKY_USER_HOME", paths.HOME), ("DECKY_USER", paths.USER),
                 ("ALLYCOMPANION_PLUGIN_DIR", paths.PLUGIN_DIR), ("DECKY_PLUGIN_SETTINGS_DIR", paths.SETTINGS_DIR),
                 ("DECKY_PLUGIN_RUNTIME_DIR", paths.RUNTIME_DIR), ("DECKY_PLUGIN_LOG_DIR", paths.LOG_DIR),
                 ("PYTHONPATH", copy_dir())):
        env += ["--setenv", f"{k}={v}"]
    r = run(["systemd-run", "--collect", f"--unit={UNIT}", f"--on-active={DELAY_S}", "--timer-property=AccuracySec=1s",
             "--timer-property=RemainAfterElapse=no",
             *env, "/usr/bin/python3", "-m", "allycompanion.cli", "cleanup"], timeout=15)
    if not r.ok:
        logger.error("could not schedule the uninstall cleanup: %s", (r.err or r.out).strip())
    return r.ok


def cancel() -> None:
    r = run(["systemctl", "stop", f"{UNIT}.timer"], timeout=10)
    if r.ok:
        logger.info("pending uninstall cleanup cancelled")
    shutil.rmtree(copy_dir(), ignore_errors=True)


def plugin_present() -> bool:
    return os.path.isfile(os.path.join(paths.PLUGIN_DIR, "plugin.json"))
