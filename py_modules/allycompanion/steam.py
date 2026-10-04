"""The Steam client as the systemd user service of the Decky user.

From Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT). In gaming mode Steam runs as
steam-launcher.service in the user's systemd instance. SteamClient.User.StartRestart re-executes
the client with the environment it already has, so anything that needs a fresh environment
(LD_PRELOAD from a drop-in) needs the service restarted instead.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from . import paths, userfs
from .log import logger
from .util import Result, run, user_ids

SERVICE = "steam-launcher.service"
UNIT_FILE = f"/usr/lib/systemd/user/{SERVICE}"


def dropin_dir() -> str:
    return os.path.join(paths.HOME, ".config", "systemd", "user", f"{SERVICE}.d")


def steam_dir() -> str:
    return os.path.join(paths.HOME, ".local", "share", "Steam")


def mkdir_user(path: str) -> None:
    """mkdir -p as the user (see userfs: root must not write into the user's directories)."""
    userfs.mkdir(path)


def write_user(path: str, data: bytes, mode: int) -> None:
    userfs.write(path, data, mode)


async def user_systemctl(*args: str, timeout: float = 30.0) -> Result:
    return await asyncio.to_thread(run, ["systemctl", "--user", *args], timeout, True)


async def daemon_reload() -> None:
    r = await user_systemctl("daemon-reload")
    if not r.ok:
        raise RuntimeError(f"systemctl --user daemon-reload failed: {(r.err or r.out).strip() or r.rc}")


async def service_state() -> str:
    r = await user_systemctl("show", "-p", "ActiveState", "--value", SERVICE, timeout=10.0)
    return r.out.strip() if r.ok else ""


def client_pids() -> List[int]:
    """PIDs of the user's `steam` client processes, newest first."""
    uid, _ = user_ids()
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() != "steam":
                    continue
            with open(f"/proc/{pid}/stat") as f:
                starttime = int(f.read().rsplit(")", 1)[1].split()[19])
        except (OSError, ValueError, IndexError):
            continue
        found.append((starttime, pid))
    return [pid for _, pid in sorted(found, reverse=True)]


def client_has_mapped(pid: int, needle: str) -> bool:
    try:
        with open(f"/proc/{pid}/maps") as f:
            return any(needle in line for line in f)
    except OSError:
        return False


async def restart() -> Dict[str, Any]:
    """Restart the client with a fresh environment; only while it runs as the user service
    (gaming mode). The frontend falls back to Steam's own restart."""
    if await service_state() not in ("active", "activating", "reloading", "deactivating"):
        return {"ok": False, "error": f"{SERVICE} is not running"}
    r = await user_systemctl("restart", "--no-block", SERVICE)
    if not r.ok:
        return {"ok": False, "error": f"systemctl --user restart failed: {(r.err or r.out).strip() or r.rc}"}
    logger.info("%s restart requested", SERVICE)
    return {"ok": True, "error": ""}


def newest_client() -> Optional[int]:
    pids = client_pids()
    return pids[0] if pids else None
