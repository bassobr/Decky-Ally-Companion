"""Subprocess and JSON helpers, and the root/user boundary.

The backend runs as root (plugin flag "root"). Anything that belongs to the user session
(systemctl --user, PipeWire, the session bus with steamos-manager's public API) must run
with as_user=True, which drops to the Decky user with that user's session environment.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

from . import paths

SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


class Result:
    __slots__ = ("rc", "out", "err")

    def __init__(self, rc: int, out: str, err: str):
        self.rc, self.out, self.err = rc, out, err

    def __repr__(self) -> str:
        return f"Result(rc={self.rc})"

    @property
    def ok(self) -> bool:
        return self.rc == 0


def user_ids() -> Tuple[int, int]:
    """uid and gid of the Decky user, taken from the owner of their home directory."""
    st = os.stat(paths.HOME)
    return st.st_uid, st.st_gid


def clean_env() -> Dict[str, str]:
    # Decky's PyInstaller runtime sets LD_LIBRARY_PATH to its bundled libraries, which breaks
    # system binaries such as curl; children never inherit the backend's environment.
    return {"PATH": SYSTEM_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": paths.HOME}


def user_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment of the user's session; Decky passes neither XDG_RUNTIME_DIR nor the bus address."""
    uid, _ = user_ids()
    runtime = f"/run/user/{uid}"
    env = clean_env()
    env.update({"USER": paths.USER, "XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus"})
    if extra:
        env.update(extra)
    return env


def _drop_kwargs() -> Dict[str, object]:
    """subprocess arguments that switch a child of root to the Decky user; empty when not root."""
    if os.geteuid() != 0:
        return {}
    uid, gid = user_ids()
    if uid == 0:
        return {}
    return {"user": uid, "group": gid, "extra_groups": os.getgrouplist(paths.USER, gid)}


def run(cmd: List[str], timeout: float = 60, as_user: bool = False, env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None, input_text: Optional[str] = None) -> Result:
    kwargs: Dict[str, object] = _drop_kwargs() if as_user else {}
    if env is None:
        env = user_env() if as_user else clean_env()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd,
                           input=input_text, **kwargs)  # type: ignore[arg-type]
        return Result(p.returncode, p.stdout, p.stderr)
    except FileNotFoundError as e:
        return Result(127, "", f"not found: {e}")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timeout after {timeout}s: {' '.join(cmd[:3])}")


def which(name: str) -> Optional[str]:
    return shutil.which(name, path=SYSTEM_PATH)


def read_text(path: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def read_json(path: str, default=None):
    """JSON from a system path (the plugin directory, /etc); files below the home go through safefs."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
