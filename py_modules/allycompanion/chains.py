"""PipeWire filter chains in their own process, as systemd user units (the speaker DSP's pattern).

Used by the microphone and headphone modules. Configs live in the user-owned audio directory;
everything that touches the user session runs as the Decky user.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from allydsp import hardware
from allydsp import paths as dsp_paths
from allydsp.util import atomic_write_text, makedirs_user, remove_file

from .log import logger
from .util import run

UNIT_TEMPLATE = """# {description}. Written by Ally Companion.
[Unit]
Description={description}
After=pipewire.service wireplumber.service
BindsTo=pipewire.service
ConditionPathExists={conf}

[Service]
Type=simple
Environment=MALLOC_ARENA_MAX=1
ExecStart=/usr/bin/pipewire -c "{conf}"
Restart=on-failure
RestartSec=1
Slice=session.slice
"""


def quote(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class UserChain:
    def __init__(self, name: str, description: str) -> None:
        self.unit = f"ally-companion-{name}.service"
        self.description = description
        self.conf = os.path.join(dsp_paths.RUNTIME_DIR, f"{name}.conf")
        self.unit_path = os.path.join(dsp_paths.HOME, ".config", "systemd", "user", self.unit)

    def systemctl(self, *args: str) -> Any:
        return run(["systemctl", "--user", *args], timeout=30, as_user=True)

    def write(self, conf_text: str) -> bool:
        """Write config and unit; True when the config changed."""
        makedirs_user(dsp_paths.RUNTIME_DIR)
        try:
            with open(self.conf, "r", encoding="utf-8") as f:
                changed = f.read() != conf_text
        except OSError:
            changed = True
        if changed:
            atomic_write_text(self.conf, conf_text)
        unit_text = UNIT_TEMPLATE.format(description=self.description, conf=self.conf)
        try:
            with open(self.unit_path, "r", encoding="utf-8") as f:
                unit_current = f.read() == unit_text
        except OSError:
            unit_current = False
        if not unit_current:
            makedirs_user(os.path.dirname(self.unit_path))
            atomic_write_text(self.unit_path, unit_text)
            self.systemctl("daemon-reload")
        return changed

    def is_active(self) -> bool:
        return self.systemctl("is-active", self.unit).out.strip() == "active"

    def start(self, restart: bool = False) -> None:
        r = self.systemctl("restart" if restart else "start", self.unit)
        if not r.ok:
            raise RuntimeError(f"{self.unit}: {(r.err or r.out).strip()[:200]}")
        logger.info("%s %s", self.unit, "restarted" if restart else "started")

    def stop(self) -> None:
        if self.is_active():
            self.systemctl("stop", self.unit)
            logger.info("%s stopped", self.unit)

    def remove(self) -> None:
        self.stop()
        remove_file(self.unit_path)
        remove_file(self.conf)
        self.systemctl("daemon-reload")


def nodes(media_class: str, dump: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Nodes of one media class: name and description."""
    out = []
    for obj in dump if dump is not None else hardware.pw_dump():
        props = ((obj.get("info") or {}).get("props") or {})
        if props.get("media.class") == media_class and props.get("node.name"):
            out.append({"name": str(props["node.name"]), "description": str(props.get("node.description") or props["node.name"])})
    return out


def node_present(name: str, dump: Optional[List[Dict[str, Any]]] = None) -> bool:
    return any(n["name"] == name for cls in ("Audio/Sink", "Audio/Source") for n in nodes(cls, dump))
