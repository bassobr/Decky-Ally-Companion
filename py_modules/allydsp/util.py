"""Subprocess, hashing, atomic file and JSON helpers.

Inside the root backend every command runs as the Decky user and every file below the home is
read through allycompanion.safefs and written through allycompanion.userfs (a child process as the
user), so symlinks planted by the user cannot redirect root. The worker runs as the user and uses
the plain operations.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from typing import Any, Dict, List, Optional

from allycompanion.util import Result, user_ids, which  # noqa: F401  (shared with the backend)
from allycompanion.util import run as _run

from . import paths


def _as_root() -> bool:
    return os.geteuid() == 0


def remove_file(path: str) -> None:
    if _as_root():
        from allycompanion import userfs
        userfs.remove(path)
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def rmtree_user(path: str) -> None:
    """Delete a directory below the home; as the user when called from the root backend."""
    if _as_root():
        from allycompanion import userfs
        userfs.rmtree(path)
        return
    shutil.rmtree(path, ignore_errors=True)


def user_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment for the user's systemd and PipeWire session; Decky does not
    pass XDG_RUNTIME_DIR or the session bus address to plugin backends."""
    uid = user_ids()[0] if _as_root() else os.getuid()
    runtime = f"/run/user/{uid}" if _as_root() else (os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": paths.HOME,
        "USER": paths.USER,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime}/bus",
    }
    if extra:
        env.update(extra)
    return env


def run(cmd: List[str], timeout: float = 60, env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None, input_text: Optional[str] = None) -> Result:
    """Always as the Decky user (inside the root backend too), as it ran in Ally DSP."""
    return _run(cmd, timeout=timeout, as_user=True, env=env if env is not None else user_env(), cwd=cwd,
                input_text=input_text)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def makedirs_user(path: str) -> None:
    """mkdir -p as the user, also when called from the root backend."""
    if _as_root():
        from allycompanion import userfs
        userfs.mkdir(path)
    else:
        os.makedirs(path, exist_ok=True)


def atomic_write_bytes(path: str, data: bytes, mode: int = 0o644) -> None:
    if _as_root():
        from allycompanion import userfs
        userfs.write(path, data, mode)
        return
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".tmp-{os.getpid()}-{os.urandom(4).hex()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: str, text: str, mode: int = 0o644) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode)


def atomic_copy(src: str, dst: str) -> None:
    with open(src, "rb") as f:
        atomic_write_bytes(dst, f.read())


def read_text(path: str) -> Optional[str]:
    """A file below the home; in the root backend as the user would read it (safefs)."""
    if _as_root():
        from allycompanion import safefs
        try:
            data = safefs.read_bytes(path)
        except OSError:
            return None
        return None if data is None else data.decode("utf-8", errors="replace")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def read_json(path: str, default: Any = None) -> Any:
    if _as_root():
        from allycompanion import safefs
        return safefs.read_json(path, default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
