"""File operations below the user's home, done by a child process running as the user.

The backend runs as root, but the directories it writes into (Steam's config, ~/.config,
~/.local, ~/Documents, the plugin's data directory) belong to the Decky user. Writing there as
root would let any process of that user redirect the write with a symlink, or swap a file between
create and chown, and so gain root. Done as the user, a redirected write lands only where the user
could write anyway. Outside root (tests, the worker), the same code runs in-process.
"""
from __future__ import annotations

import os
import subprocess
from typing import List

HELPER = r"""
import os, shutil, sys, zipfile
op, args = sys.argv[1], sys.argv[2:]
if op == "write":
    path, mode = args[0], int(args[1], 8)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp, "wb") as f:
        f.write(sys.stdin.buffer.read())
    os.chmod(tmp, mode)
    os.replace(tmp, path)
elif op == "mkdir":
    os.makedirs(args[0], exist_ok=True)
elif op == "remove":
    for p in args:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
elif op == "rmdir":
    for p in args:
        try:
            os.rmdir(p)
        except OSError:
            pass
elif op == "rmtree":
    for p in args:
        shutil.rmtree(p, ignore_errors=True)
elif op == "unzip":
    archive, dest = args
    names = []
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            base = os.path.basename(name)
            if not base or name.endswith("/"):
                continue
            with z.open(name) as src, open(os.path.join(dest, base), "wb") as dst:
                shutil.copyfileobj(src, dst)
            names.append(base)
    print("\n".join(names))
else:
    sys.exit("unknown op " + op)
"""

PYTHON = "/usr/bin/python3"


def _run(op: str, args: List[str], data: bytes = b"", timeout: float = 60) -> str:
    from .util import _drop_kwargs, user_env  # util imports nothing from here

    as_root = os.geteuid() == 0
    p = subprocess.run([PYTHON if os.path.exists(PYTHON) else "python3", "-c", HELPER, op, *args], input=data,
                       capture_output=True, timeout=timeout, env=user_env() if as_root else None,
                       **(_drop_kwargs() if as_root else {}))  # type: ignore[arg-type]
    if p.returncode != 0:
        raise OSError(f"{op} {args[:1]} as the user failed: {p.stderr.decode(errors='replace').strip()[-200:]}")
    return p.stdout.decode(errors="replace")


def write(path: str, data: bytes, mode: int = 0o644) -> None:
    _run("write", [path, oct(mode)], data)


def write_text(path: str, text: str, mode: int = 0o644) -> None:
    write(path, text.encode("utf-8"), mode)


def mkdir(path: str) -> None:
    _run("mkdir", [path])


def remove(*paths: str) -> None:
    if paths:
        _run("remove", list(paths))


def rmdir(*paths: str) -> None:
    if paths:
        _run("rmdir", list(paths))


def rmtree(*paths: str) -> None:
    if paths:
        _run("rmtree", list(paths))


def unzip(archive: str, dest: str) -> List[str]:
    return [n for n in _run("unzip", [archive, dest], timeout=120).splitlines() if n]
