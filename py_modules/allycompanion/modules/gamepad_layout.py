"""Gamepad layout: hide the inputs the ROG Xbox Ally does not have from Steam Input.

Ported from the Gamepad Layout Fix of Ally Fix (https://github.com/lonsdaleite/Ally-Fix, MIT).

Steam builds the Ally's capability mask from a constant in steamclient.so and shows trackpads,
capacitive sticks and four rear buttons. Two layers:

- native: bin/liballycaps.so, an LD_PRELOAD shim for the `steam` process that patches the
  capability constant in memory (TRACKPAD and CAPJOYSTICK cleared). It reaches the client through
  a drop-in of steam-launcher.service, so it takes effect when the service restarts.
- UI: the frontend edits Steam's button metadata and clears the GRIPS bit on the controller
  objects, which removes the lower rear pair (src/layoutPatch.ts); it reports the result here.

Both layers fail towards stock.
"""
from __future__ import annotations

import asyncio
import glob
import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

from .. import device, paths, steam
from ..log import logger
from ..module import Module

LIB_NAME = "liballycaps.so"
MASK = 0x60AFFF  # stock 0x160bfff without TRACKPAD (bit 12) and CAPJOYSTICK (bit 24)
MARKER = "# managed by Ally Companion (gamepad layout)"
# Ally Fix's layout; removed when this module takes over.
LEGACY_DROPIN_NAME = "zz-ally-fix-gamepad-layout.conf"
LEGACY_LIB_DIRNAME = "ally-fix"


def lib_dir() -> str:
    # LD_PRELOAD splits on spaces and the plugin directory has one, so the shim is copied here.
    return os.path.join(paths.HOME, ".local", "lib", "ally-companion")


def libs() -> Dict[str, str]:
    # The client is 32-bit, but LD_PRELOAD reaches every 64-bit child of the service too; `$LIB`
    # expands to lib32 or lib, and the 64-bit twin is a no-op outside the `steam` process.
    return {
        os.path.join(lib_dir(), "lib32", LIB_NAME): os.path.join(paths.PLUGIN_DIR, "bin", LIB_NAME),
        os.path.join(lib_dir(), "lib", LIB_NAME): os.path.join(paths.PLUGIN_DIR, "bin", "liballycaps64.so"),
    }


def preload_entry() -> str:
    return os.path.join(lib_dir(), "$LIB", LIB_NAME)


def dropin() -> str:
    return os.path.join(steam.dropin_dir(), "zz-ally-companion-gamepad-layout.conf")  # sorts last: wins


def shim_log() -> str:
    return os.path.join(paths.HOME, ".local", "state", "ally-companion-allycaps.log")


def steamclient() -> str:
    return os.path.join(steam.steam_dir(), "ubuntu12_32", "steamclient.so")


def dropin_dirs() -> Tuple[str, ...]:
    return (
        f"/usr/lib/systemd/user/{steam.SERVICE}.d",
        f"/usr/local/lib/systemd/user/{steam.SERVICE}.d",
        f"/run/systemd/user/{steam.SERVICE}.d",
        f"/etc/systemd/user/{steam.SERVICE}.d",
        steam.dropin_dir(),
    )


def read(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def preload_from(text: Optional[bytes], current: List[str]) -> List[str]:
    """Apply the Environment= lines of one unit or drop-in to an LD_PRELOAD list."""
    if text is None:
        return current
    for line in text.decode(errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if not sep or key.strip() != "Environment":
            continue
        value = value.strip()
        if not value:  # `Environment=` resets everything
            current = []
            continue
        try:
            tokens = shlex.split(value)
        except ValueError:
            continue
        for tok in tokens:
            if tok.startswith("LD_PRELOAD="):
                current = [p for p in tok[len("LD_PRELOAD="):].replace(":", " ").split() if p]
    return current


class GamepadLayout(Module):
    id = "gamepad_layout"
    title = "Gamepad layout"
    toggle = True
    defaults = {"enabled": False}

    def __init__(self) -> None:
        super().__init__()
        self.ui_result: Optional[Dict[str, Any]] = None

    def actions(self):
        return {"report_ui": self.report_ui}

    def supported(self) -> Tuple[bool, str]:
        if not device.is_xbox_ally():
            return False, f"needs a ROG Xbox Ally (board {device.board() or 'unknown'})"
        if not os.path.isfile(steam.UNIT_FILE):
            return False, f"{steam.SERVICE} not found (SteamOS gaming mode only)"
        if not all(os.path.isfile(src) for src in libs().values()):
            return False, f"{LIB_NAME} missing from the plugin"
        if not os.path.isfile(steamclient()):
            return False, "32-bit steamclient.so not found"
        return True, ""

    # ------------------------------------------------------------- drop-in
    def other_preload(self) -> List[str]:
        """LD_PRELOAD as the other drop-ins leave it; a drop-in replaces the variable, so ours
        repeats theirs."""
        files: Dict[str, str] = {}
        for d in dropin_dirs():
            for path in glob.glob(os.path.join(d, "*.conf")):
                files[os.path.basename(path)] = path
        preload = preload_from(read(steam.UNIT_FILE), [])
        for name in sorted(files):
            if files[name] == dropin() or name == LEGACY_DROPIN_NAME:
                continue
            preload = preload_from(read(files[name]), preload)
        legacy = os.path.join(paths.HOME, ".local", "lib", LEGACY_LIB_DIRNAME) + "/"
        return [p for p in preload if p != preload_entry() and not p.startswith(lib_dir() + "/") and not p.startswith(legacy)]

    def dropin_text(self) -> str:
        preload = ":".join([*self.other_preload(), preload_entry()])
        return (f"{MARKER}\n[Service]\nEnvironment=LD_PRELOAD={preload}\n"
                f"Environment=ALLYCAPS_MASK={MASK:#x}\nEnvironment=ALLYCAPS_LOG={shim_log()}\n")

    def lib_current(self) -> bool:
        return all((data := read(src)) is not None and read(dst) == data for dst, src in libs().items())

    def dropin_current(self) -> bool:
        return read(dropin()) == self.dropin_text().encode()

    def is_applied(self) -> bool:
        return self.lib_current() and self.dropin_current()

    def shim_state(self) -> Tuple[bool, Optional[bool]]:
        """(loaded into the running client, patched the constant); patched is None until the log
        has a line for this process."""
        pid = steam.newest_client()
        if pid is None or not steam.client_has_mapped(pid, "/" + LIB_NAME):
            return False, None
        patched: Optional[bool] = None
        text = read(shim_log())
        if text is not None:
            tag = f"[{pid}]"
            for line in text.decode(errors="replace").splitlines():
                if tag not in line:
                    continue
                if "patched caps const" in line:
                    patched = True
                elif "NOT patching" in line or "failed" in line:
                    patched = False
        return True, patched

    def details(self) -> Dict[str, Any]:
        loaded, patched = self.shim_state()
        return {"nativeReady": self.is_applied(), "shimActive": loaded, "shimPatched": patched,
                "ui": self.ui_result, "restartPending": self.enabled != loaded}

    def refine(self, state: str, message: str, details: Dict[str, Any]) -> Tuple[str, str]:
        if state == "error":
            return state, message
        loaded, patched, ui = details.get("shimActive"), details.get("shimPatched"), self.ui_result
        if self.enabled and state == "applied":
            if not loaded:
                return "restart_pending", "Restart Steam to apply"
            if patched is False:
                return "error", "capability constant not found in steamclient.so (Steam update?)"
            if ui is not None and not ui.get("ok"):
                return "error", f"UI patch failed: {ui.get('error') or ui.get('stage') or 'unknown'}"
            if ui is not None and ui.get("art") not in (None, "ok"):
                return state, f"controller picture not applied: {ui.get('art')}"
        elif not self.enabled and loaded:
            return "restart_pending", "Restart Steam to finish turning this off"
        return state, message

    # ------------------------------------------------------------- apply / revert
    async def apply(self) -> None:
        changed = self._remove_legacy()
        for dst, src in libs().items():
            data = read(src)
            if data is None:
                raise RuntimeError(f"{src} unreadable")
            if read(dst) != data:
                steam.write_user(dst, data, 0o755)
                changed = True
        steam.mkdir_user(os.path.dirname(shim_log()))  # the shim only appends
        if not self.dropin_current():
            steam.write_user(dropin(), self.dropin_text().encode(), 0o644)
            changed = True
        if changed:
            logger.info("[gamepad_layout] drop-in written")
            await steam.daemon_reload()

    async def revert(self) -> None:
        self.ui_result = None
        changed = self._remove_legacy()
        if os.path.exists(dropin()):
            os.remove(dropin())
            changed = True
        for dst in libs():
            if os.path.exists(dst):
                os.remove(dst)
        for d in [*(os.path.dirname(p) for p in libs()), lib_dir()]:
            try:
                os.rmdir(d)
            except OSError:
                pass
        if changed:
            logger.info("[gamepad_layout] drop-in removed")
            await steam.daemon_reload()

    def _remove_legacy(self) -> bool:
        """Ally Fix's drop-in and shim copy, if it was removed without cleaning up."""
        legacy = os.path.join(steam.dropin_dir(), LEGACY_DROPIN_NAME)
        if not os.path.exists(legacy):
            return False
        os.remove(legacy)
        legacy_dir = os.path.join(paths.HOME, ".local", "lib", LEGACY_LIB_DIRNAME)
        for root, dirs, files in os.walk(legacy_dir, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
            for d in dirs:
                os.rmdir(os.path.join(root, d))
        if os.path.isdir(legacy_dir):
            os.rmdir(legacy_dir)
        logger.info("[gamepad_layout] Ally Fix's drop-in removed")
        return True

    async def report_ui(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.ui_result = result if isinstance(result, dict) else None
        if self.ui_result and not self.ui_result.get("ok"):
            logger.warning("[gamepad_layout] UI patch: %s", self.ui_result)
        else:
            logger.info("[gamepad_layout] UI patch: %s", self.ui_result)
        await asyncio.sleep(0)
