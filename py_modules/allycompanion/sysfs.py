"""sysfs reads and writes; every path goes through paths.sys_path so tests can fake the tree."""
from __future__ import annotations

import glob
import os
from typing import List, Optional

from . import paths
from .log import logger


def p(rel: str) -> str:
    return paths.sys_path(rel)


def read_str(path: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path: str, default: Optional[int] = None) -> Optional[int]:
    v = read_str(path)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def write_str(path: str, value: str) -> None:
    """Raises OSError when the kernel rejects the value."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(value)


def try_write(path: str, value: str, tag: str = "") -> bool:
    try:
        write_str(path, value)
        return True
    except OSError as e:
        logger.warning("%s write %r -> %s failed: %s", tag, value, path, e)
        return False


def sorted_glob(rel_pattern: str) -> List[str]:
    return sorted(glob.glob(p(rel_pattern)))


def find_hwmon(name: str) -> Optional[str]:
    for d in sorted_glob("sys/class/hwmon/hwmon*"):
        if read_str(os.path.join(d, "name")) == name:
            return d
    return None


def dmi(field: str) -> str:
    return read_str(p(f"sys/class/dmi/id/{field}"), "") or ""
