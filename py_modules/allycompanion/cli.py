"""Support CLI: `sudo PYTHONPATH=py_modules python3 -m allycompanion.cli diagnostics` in the plugin dir."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys

from . import cleanup, device, diagnostics, paths, settings
from .log import logger


async def _uninstall_all() -> None:
    from .modules import MODULES
    from .module import Context
    from .registry import Registry

    reg = Registry(MODULES)
    s = settings.load(reg.defaults())

    async def emit(event, payload):
        return None

    reg.bind(s, Context(lambda: None, emit))
    await reg.uninstall()


def run_cleanup() -> int:
    if cleanup.plugin_present():
        logger.info("plugin is back; nothing to clean up")
        return 0
    asyncio.run(_uninstall_all())
    shutil.rmtree(paths.RUNTIME_DIR, ignore_errors=True)
    logger.info("Ally Companion removed: modules reverted, runtime data deleted")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="allycompanion.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="device and system stack as JSON")
    sub.add_parser("diagnostics", help="full diagnostics report")
    sub.add_parser("cleanup", help="revert all modules if the plugin was removed (used by the uninstall timer)")
    a = ap.parse_args(argv)
    if a.cmd == "info":
        print(json.dumps({"device": device.info(), "stack": device.stack()}, indent=2))
    elif a.cmd == "cleanup":
        return run_cleanup()
    else:
        print(diagnostics.render_text(diagnostics.collect()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
