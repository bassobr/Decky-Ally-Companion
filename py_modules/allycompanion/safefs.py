"""Root-safe file access below the user's home.

The backend runs as root, but everything below the home directory belongs to the Decky user, who
can plant symlinks, FIFOs or hard links there. Reads walk every component below the home without
following symlinks and accept only regular files the user could read as well; a path that does
not qualify is read by a child process running as the user instead (userfs), which follows
symlinks with the user's permissions only. Either way root never reads more than the user could.

The one file root writes below the home, its own settings.json, is replaced through a directory
opened the same way, so a planted symlink cannot move the write elsewhere. Paths outside the home
are system paths and used as they are.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from typing import Any, List, Optional, Tuple

from . import paths, userfs
from .log import logger

MAX_READ = 8 << 20  # settings, configs, lists; larger files are refused
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC


class Refused(OSError):
    """The path exists but is not something root may open on the user's behalf."""


def below_home(path: str) -> Optional[List[str]]:
    """Components of `path` below the home directory; None for a path outside it."""
    home = os.path.normpath(paths.HOME)
    full = os.path.normpath(os.path.abspath(path))
    if full == home or not full.startswith(home.rstrip(os.sep) + os.sep):
        return None
    return full[len(home.rstrip(os.sep)) + 1:].split(os.sep)


def _user() -> Tuple[int, Tuple[int, ...]]:
    st = os.stat(paths.HOME)
    try:
        groups = tuple(os.getgrouplist(paths.USER, st.st_gid))
    except (KeyError, OSError):
        groups = (st.st_gid,)
    return st.st_uid, groups


def _allowed(st: os.stat_result, bits: Tuple[int, int, int], user: Tuple[int, Tuple[int, ...]]) -> bool:
    """Permission check as the user: owner, group or other bits."""
    uid, groups = user
    if st.st_uid == uid:
        return bool(st.st_mode & bits[0])
    if st.st_gid in groups:
        return bool(st.st_mode & bits[1])
    return bool(st.st_mode & bits[2])


_READ = (stat.S_IRUSR, stat.S_IRGRP, stat.S_IROTH)
_SEARCH = (stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH)


def _walk(parts: List[str], user: Tuple[int, Tuple[int, ...]]) -> int:
    """fd of the directory `parts` names below the home, no symlinks on the way."""
    fd = os.open(os.path.realpath(paths.HOME), os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC)
    try:
        for part in parts:
            if part in ("", ".", ".."):
                raise Refused(errno.EINVAL, f"unexpected path component {part!r}")
            try:
                nfd = os.open(part, _DIR, dir_fd=fd)
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK, errno.EACCES):
                    raise Refused(e.errno, f"{part}: not a plain directory") from e
                raise
            os.close(fd)
            fd = nfd
            if not _allowed(os.fstat(fd), _SEARCH, user):
                raise Refused(errno.EACCES, f"{part}: not searchable for the user")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open(path: str, parts: List[str]) -> Optional[int]:
    """Read-only fd of a regular file the user could read; None when it does not exist."""
    user = _user()
    try:
        dfd = _walk(parts[:-1], user)
    except FileNotFoundError:
        return None
    try:
        fd = os.open(parts[-1], _FILE, dir_fd=dfd)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK, errno.EACCES):  # EACCES: only without root
            raise Refused(e.errno, f"{path}: symlink or not readable") from e
        raise
    finally:
        os.close(dfd)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or not _allowed(st, _READ, user):
        os.close(fd)
        raise Refused(errno.EACCES, f"{path}: not a regular file the user can read")
    return fd


def read_bytes(path: str, limit: int = MAX_READ, tail: bool = False) -> Optional[bytes]:
    """Content of a file below the home as the user would read it (None: it does not exist).
    `tail` returns the last `limit` bytes of a larger file instead of refusing it."""
    parts = below_home(path)
    if parts is None:
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
    try:
        fd = _open(path, parts)
    except Refused as e:
        logger.info("reading %s as the user: %s", path, e)
        return userfs.read(path, limit, tail)
    if fd is None:
        return None
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size > limit:
            if not tail:
                raise Refused(errno.EFBIG, f"{path}: larger than {limit} bytes")
            f.seek(size - limit)
        data = f.read(limit + 1)
    if len(data) > limit:
        if not tail:
            raise Refused(errno.EFBIG, f"{path}: larger than {limit} bytes")
        data = data[-limit:]
    return data


def read_text(path: str, limit: int = MAX_READ) -> Optional[str]:
    """UTF-8 text of a file below the home; raises ValueError for anything else."""
    data = read_bytes(path, limit)
    return None if data is None else data.decode("utf-8")


def read_json(path: str, default: Any = None, limit: int = MAX_READ) -> Any:
    try:
        data = read_bytes(path, limit)
        return default if data is None else json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as e:
        if not isinstance(e, FileNotFoundError):
            logger.warning("%s not read: %s", path, e)
        return default


def sha256(path: str, limit: int) -> str:
    """SHA-256 of a file below the home, hashed as the user (downloads may sit behind links)."""
    if below_home(path) is None:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    return userfs.sha256(path, limit)


def stat_file(path: str) -> Optional[os.stat_result]:
    """lstat of a regular file below the home without following links on the way; None otherwise."""
    parts = below_home(path)
    if parts is None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        return st if stat.S_ISREG(st.st_mode) else None
    try:
        dfd = _walk(parts[:-1], _user())
    except OSError:
        return None
    try:
        st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
    except OSError:
        return None
    finally:
        os.close(dfd)
    return st if stat.S_ISREG(st.st_mode) else None


def write_bytes(path: str, data: bytes, mode: int = 0o644) -> None:
    """Atomically replace a root-owned file (settings.json) in the real directory below the home."""
    parts = below_home(path)
    if parts is None:
        d = os.path.dirname(path) or "."
        dfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC)
        name = os.path.basename(path)
    else:
        dfd = _walk(parts[:-1], _user())
        name = parts[-1]
    tmp = f".{name}.tmp-{os.getpid()}-{os.urandom(4).hex()}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC, 0o600, dir_fd=dfd)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                os.fchmod(f.fileno(), mode)
            os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)  # replaces atomically (POSIX)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
            raise
    finally:
        os.close(dfd)
