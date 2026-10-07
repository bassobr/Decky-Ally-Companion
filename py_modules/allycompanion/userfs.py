"""File operations below the user's home, done by a child process running as the user.

The backend runs as root, but the directories it writes into (Steam's config, ~/.config,
~/.local, ~/Documents, the plugin's data directory) belong to the Decky user. Writing there as
root would let any process of that user redirect the write with a symlink, or swap a file between
create and chown, and so gain root. Done as the user, a redirected write lands only where the user
could write anyway. Reads that safefs cannot do in-process (symlinked paths, downloads) come here
too, so root never reads more than the user could. Outside root (tests, the worker) the child runs
as the current user.
"""
from __future__ import annotations

import errno
import json
import os
import subprocess
from typing import List, Optional, Tuple

HELPER = r"""
import hashlib, json, os, shutil, stat, sys, zipfile
op, args = sys.argv[1], sys.argv[2:]


def open_regular(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        sys.exit(3)
    f = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        sys.exit("not a regular file")
    return f


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
elif op == "read":
    path, limit, tail = args[0], int(args[1]), args[2] == "1"
    with open_regular(path) as f:
        size = os.fstat(f.fileno()).st_size
        if size > limit:
            if not tail:
                sys.exit("larger than %d bytes" % limit)
            f.seek(size - limit)
        sys.stdout.buffer.write(f.read(limit))
elif op == "sha256":
    path, limit = args[0], int(args[1])
    h, n = hashlib.sha256(), 0
    with open_regular(path) as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += len(chunk)
            if n > limit:
                sys.exit("larger than %d bytes" % limit)
            h.update(chunk)
    print(h.hexdigest())
elif op == "listdir":
    out = []
    try:
        names = os.listdir(args[0])
    except FileNotFoundError:
        names = []
    for name in names:
        try:
            st = os.stat(os.path.join(args[0], name))
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out.append([name, st.st_size])
    print(json.dumps(out))
else:
    sys.exit("unknown op " + op)
"""

PYTHON = "/usr/bin/python3"


NOT_FOUND = 3


def _run(op: str, args: List[str], data: bytes = b"", timeout: float = 60) -> bytes:
    from .util import _drop_kwargs, user_env  # util imports nothing from here

    as_root = os.geteuid() == 0
    # -I: no current directory, user site or PYTHON* variables in the child's import path
    p = subprocess.run([PYTHON if os.path.exists(PYTHON) else "python3", "-I", "-c", HELPER, op, *args], input=data,
                       capture_output=True, timeout=timeout, env=user_env() if as_root else None,
                       **(_drop_kwargs() if as_root else {}))  # type: ignore[arg-type]
    if p.returncode == NOT_FOUND:
        raise FileNotFoundError(errno.ENOENT, "not found", args[0] if args else "")
    if p.returncode != 0:
        raise OSError(f"{op} {args[:1]} as the user failed: {p.stderr.decode(errors='replace').strip()[-200:]}")
    return p.stdout


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
    return [n for n in _run("unzip", [archive, dest], timeout=120).decode(errors="replace").splitlines() if n]


def read(path: str, limit: int, tail: bool = False) -> Optional[bytes]:
    """Content of a regular file as the user reads it; None when it does not exist."""
    try:
        return _run("read", [path, str(limit), "1" if tail else "0"])
    except FileNotFoundError:
        return None


def sha256(path: str, limit: int) -> str:
    return _run("sha256", [path, str(limit)], timeout=300).decode().strip()


def listdir(path: str) -> List[Tuple[str, int]]:
    """Regular files in a directory as the user sees them: (name, size)."""
    return [(str(n), int(size)) for n, size in json.loads(_run("listdir", [path]).decode() or "[]")]
