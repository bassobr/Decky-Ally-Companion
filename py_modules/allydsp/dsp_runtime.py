"""systemd user unit that runs `pipewire -c` with the active preset."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from . import confgen, hardware, paths
from .constants import INPUT_NODE
from .log import logger
from .util import atomic_copy, atomic_write_text, read_json, read_text, remove_file, rmtree_user, run, write_json

ACTIVE_CONF = os.path.join(paths.ACTIVE_DIR, "chain.conf")
ACTIVE_IRS = os.path.join(paths.ACTIVE_DIR, "ir.irs")
ACTIVE_META = os.path.join(paths.ACTIVE_DIR, "meta.json")

_active: Tuple[float, bool] = (0.0, False)  # last is-active answer and when
_active_lock = threading.Lock()


def systemctl(*args: str, timeout: float = 30) -> Any:
    return run(["systemctl", "--user", *args], timeout=timeout)


def unit_text() -> str:
    with open(paths.UNIT_TEMPLATE, "r", encoding="utf-8") as f:
        tmpl = f.read()
    return tmpl.replace("{lv2_path}", paths.LV2_DIR).replace("{conf_path}", ACTIVE_CONF)


def unit_installed() -> bool:
    return read_text(paths.UNIT_PATH) == unit_text()


def install_unit() -> None:
    os.makedirs(os.path.dirname(paths.UNIT_PATH), exist_ok=True)
    atomic_write_text(paths.UNIT_PATH, unit_text())
    r = systemctl("daemon-reload")
    if not r.ok:
        raise RuntimeError(f"systemctl daemon-reload failed: {r.err.strip()[:200]}")
    logger.info("installed unit %s", paths.UNIT_PATH)


def ensure_unit() -> None:
    if not unit_installed():
        install_unit()


def _remember(value: bool) -> None:
    global _active
    with _active_lock:
        _active = (time.monotonic(), value)


def is_active(max_age: float = 0.0) -> bool:
    """systemctl is-active; `max_age` reuses an answer that young (one status round)."""
    with _active_lock:
        at, value = _active
    if max_age and time.monotonic() - at < max_age:
        return value
    value = systemctl("is-active", paths.UNIT_NAME).out.strip() == "active"
    _remember(value)
    return value


def is_enabled() -> bool:
    return systemctl("is-enabled", paths.UNIT_NAME).out.strip() == "enabled"


def enable(on: bool = True) -> None:
    r = systemctl("enable" if on else "disable", paths.UNIT_NAME)
    if not r.ok and "does not exist" not in r.err:
        logger.warning("systemctl %s failed: %s", "enable" if on else "disable", r.err.strip()[:200])


def start() -> bool:
    _remember(False)
    ok = systemctl("start", paths.UNIT_NAME).ok
    _remember(ok)
    return ok


def stop() -> bool:
    ok = systemctl("stop", paths.UNIT_NAME).ok
    _remember(False)
    return ok


def restart() -> bool:
    _remember(False)
    ok = systemctl("restart", paths.UNIT_NAME).ok
    _remember(ok)
    return ok


def active_meta() -> Optional[Dict[str, Any]]:
    return read_json(ACTIVE_META)


def verify(timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    while True:
        if hardware.filter_node_present(hardware.pw_dump(), INPUT_NODE):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.4)


def apply_preset(profile: str, voicing: str, pregain_db: float = 0.0, restart_unit: bool = True) -> Dict[str, Any]:
    from .convert import preset_dir, preset_meta
    src = preset_dir(profile, voicing)
    conf_path = os.path.join(src, "chain.conf")
    irs_path = os.path.join(src, "ir.irs")
    if not (os.path.isfile(conf_path) and os.path.isfile(irs_path)):
        raise RuntimeError(f"preset {profile}/{voicing} not available")
    meta = preset_meta(profile, voicing) or {}
    with open(conf_path, "r", encoding="utf-8") as f:
        conf = f.read()
    applied_gain = False
    if abs(pregain_db) > 1e-9:
        conf, applied_gain = confgen.set_pregain_db(conf, pregain_db, meta.get("limiter_input_gain"))
    os.makedirs(paths.ACTIVE_DIR, exist_ok=True)
    atomic_copy(irs_path, ACTIVE_IRS)
    atomic_write_text(ACTIVE_CONF, conf)
    active = {"profile": profile, "voicing": voicing, "preGainDb": pregain_db if applied_gain else 0.0,
              "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "preset": meta}
    write_json(ACTIVE_META, active)
    ensure_unit()
    if restart_unit:
        if not restart():
            raise RuntimeError(f"systemctl --user restart {paths.UNIT_NAME} failed")
        active["verified"] = verify()
        if not active["verified"]:
            logger.warning("filter node not visible after restart: %s", journal(8))
    return active


def journal(lines: int = 20) -> str:
    r = run(["journalctl", "--user", "-u", paths.UNIT_NAME, "-n", str(lines), "--no-pager", "-o", "cat"], timeout=20)
    return r.out.strip() if r.ok else r.err.strip()


def status(with_journal: bool = True) -> Dict[str, Any]:
    dump = hardware.pw_dump()
    return {
        "unit_installed": os.path.isfile(paths.UNIT_PATH),
        "unit_current": unit_installed(),
        "enabled": is_enabled(),
        "active": is_active(),
        "verified": hardware.filter_node_present(dump, INPUT_NODE),
        "links": hardware.filter_links(dump),
        "active_preset": active_meta(),
        "journal": journal(12) if with_journal else "",
    }


def remove_unit() -> None:
    stop()
    enable(False)
    remove_file(paths.UNIT_PATH)
    systemctl("daemon-reload")
    rmtree_user(paths.ACTIVE_DIR)
