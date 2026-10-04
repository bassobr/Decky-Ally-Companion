"""Game profiles: per-game lighting and vibration strength.

Each entry may hold a `lighting` part (mode, colours, brightness, speed) and a `vibration` part
(left/right strength). When the game starts, the parts go to the lighting and vibration modules as
overrides; when it ends, the overrides are cleared. Per-game speaker presets stay with the audio
module (its perApp list), which the UI shows next to these.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..log import logger
from ..module import Module

PARTS = ("lighting", "vibration")


class Profiles(Module):
    id = "profiles"
    title = "Game profiles"
    defaults = {"apps": {}}

    def __init__(self) -> None:
        super().__init__()
        self.running_app: Optional[str] = None

    def actions(self):
        return {"set_app": self.set_app, "remove_app": self.remove_app}

    def apps(self) -> Dict[str, Any]:
        a = self.cfg.get("apps")
        return dict(a) if isinstance(a, dict) else {}

    def details(self) -> Dict[str, Any]:
        return {"apps": self.apps(), "runningApp": self.running_app}

    async def on_app_changed(self, app_id: Optional[str]) -> None:
        self.running_app = app_id
        await self._push(self.apps().get(app_id) if app_id else None)

    async def _push(self, entry: Optional[Dict[str, Any]]) -> None:
        mods = self.ctx.modules if self.ctx else {}
        blocked = self.ctx.blocked if self.ctx else {}
        for part in PARTS:
            m = mods.get(part)
            if m is None or part in blocked or not m.supported()[0]:
                continue
            values = (entry or {}).get(part)
            try:
                await m.set_override(values if values else None)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                logger.exception("[profiles] %s override failed", part)

    async def set_app(self, appId: str, part: str, values: Optional[Dict[str, Any]] = None, name: str = "") -> None:  # noqa: N803
        """Set (values) or clear (None) one part of a game's profile."""
        if part not in PARTS:
            raise ValueError(f"unknown part {part!r}")
        apps = self.apps()
        entry = dict(apps.get(str(appId)) or {})
        if name:
            entry["name"] = str(name)[:80]
        if values:
            entry[part] = dict(values)
        else:
            entry.pop(part, None)
        if any(p in entry for p in PARTS):
            apps[str(appId)] = entry
        else:
            apps.pop(str(appId), None)
        self.update_cfg({"apps": apps})
        if str(appId) == self.running_app:
            await self._push(apps.get(str(appId)))

    async def remove_app(self, appId: str) -> None:  # noqa: N803
        apps = self.apps()
        apps.pop(str(appId), None)
        self.update_cfg({"apps": apps})
        if str(appId) == self.running_app:
            await self._push(None)
