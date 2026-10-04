"""Subprocess, hashing, atomic file and JSON helpers."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from . import paths


class Result:
    __slots__ = ("rc", "out", "err")

    def __init__(self, rc: int, out: str, err: str):
        self.rc, self.out, self.err = rc, out, err

    def __repr__(self) -> str:
        return f"Result(rc={self.rc})"

    @property
    def ok(self) -> bool:
        return self.rc == 0


def user_ids() -> "tuple[int, int]":
    st = os.stat(paths.HOME)
    return st.st_uid, st.st_gid


def _drop() -> Dict[str, object]:
    """Inside the root backend every command runs as the Decky user, as it did in Ally DSP."""
    if os.geteuid() != 0:
        return {}
    uid, gid = user_ids()
    return {} if uid == 0 else {"user": uid, "group": gid, "extra_groups": os.getgrouplist(paths.USER, gid)}


def chown_user(path: str) -> None:
    """Files the root backend writes below the user's home stay the user's."""
    if os.geteuid() == 0:
        uid, gid = user_ids()
        os.chown(path, uid, gid)


def user_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment for the user's systemd and PipeWire session; Decky does not
    pass XDG_RUNTIME_DIR or the session bus address to plugin backends."""
    uid = user_ids()[0] if os.geteuid() == 0 else os.getuid()
    runtime = f"/run/user/{uid}" if os.geteuid() == 0 else (os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}")
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
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env if env is not None else user_env(), cwd=cwd, input=input_text,
                           **_drop())  # type: ignore[arg-type]
        return Result(p.returncode, p.stdout, p.stderr)
    except FileNotFoundError as e:
        return Result(127, "", f"not found: {e}")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timeout after {timeout}s: {' '.join(cmd[:3])}")


def which(name: str) -> Optional[str]:
    return shutil.which(name, path="/usr/local/bin:/usr/bin:/bin")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def makedirs_user(path: str) -> None:
    """mkdir -p whose new directories belong to the user, also when root creates them."""
    missing = []
    d = path
    while d and not os.path.isdir(d):
        missing.append(d)
        d = os.path.dirname(d)
    for m in reversed(missing):
        os.makedirs(m, exist_ok=True)
        chown_user(m)


def atomic_write_bytes(path: str, data: bytes, mode: int = 0o644) -> None:
    d = os.path.dirname(path) or "."
    makedirs_user(d)
    tmp = os.path.join(d, f".tmp-{os.getpid()}-{os.urandom(4).hex()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        chown_user(tmp)
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


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def human_bytes(n: Optional[float]) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def parse_size(text: str) -> Optional[int]:
    """'10.33 MB' -> bytes (approximate, decimal-friendly for progress bars)."""
    try:
        num, unit = text.strip().split()
        mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[unit.upper()]
        return int(float(num) * mult)
    except (ValueError, KeyError):
        return None
