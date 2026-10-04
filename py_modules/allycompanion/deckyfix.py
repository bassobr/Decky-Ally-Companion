"""Work around a Decky Loader bug that keeps plugin backends from shutting down.

To stop a plugin Decky sends SIGTERM and then closes its end of the plugin socket. In the
plugin process, localsocket.UnixSocket._listen_for_method_call then gets an empty line
from _read_single_line at EOF in a loop that never yields, so the event loop never runs
the shutdown (_unload, _uninstall) and Decky kills the process 5 s later
(Decky v3.2.9 and v3.2.10-pre1; reported as SteamDeckHomebrew/decky-loader#975).
Letting the read wait forever once the reader is at EOF stops the spin.
"""
from __future__ import annotations

import asyncio
import sys

MODULES = ("decky_loader.localplatform.localsocket", "localplatform.localsocket")


def park_reader_at_eof() -> bool:
    """Patch Decky's socket class in this process; False when it is not there."""
    for name in MODULES:
        cls = getattr(sys.modules.get(name), "UnixSocket", None)
        original = getattr(cls, "_read_single_line", None)
        if original is not None:
            break
    else:
        return False
    if getattr(original, "parks_at_eof", False):
        return True

    async def read_single_line(self, reader, *args, **kwargs):
        if getattr(reader, "at_eof", None) and reader.at_eof():
            await asyncio.Event().wait()  # the loader closed the connection; the process is stopping
        return await original(self, reader, *args, **kwargs)

    read_single_line.parks_at_eof = True
    cls._read_single_line = read_single_line
    return True
