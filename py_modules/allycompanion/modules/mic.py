"""Microphone noise suppression: RNNoise in front of the internal microphone.

The cleaned signal is a virtual microphone whose session priority is above the internal one, so it
becomes the default source while it exists; when the module is off the node goes away and the
default falls back. (A WirePlumber smart filter does not work here: Valve's loopback source in front
of the microphone is a filter itself, and WirePlumber then only looks for smart filters of the
loopback's own link group.)

SteamOS ships NoiseTorch's build of the plugin (/usr/lib/ladspa/rnnoise_ladspa.so): one mono plugin
labelled "nt-filter" with a control literally named "VAD %%"; filter-chain runs one copy per
channel. PipeWire's own example names a different build (librnnoise_ladspa, noise_suppressor_stereo).
"""
from __future__ import annotations

import asyncio
import math
import os
from typing import Any, Dict, Optional, Tuple

from allydsp import confgen

from .. import chains
from ..log import logger
from ..module import Module

LADSPA = "/usr/lib/ladspa/rnnoise_ladspa.so"
NODE = "ally_companion_mic"
PRIORITY = 2500  # Valve's loopback source of the internal microphone has 2010
VAD_MAX = 95.0
STATUS_AGE_S = 2.0  # one systemctl/pw-dump answer serves a whole status round


def clean_vad(v: Any, default: float = 50.0) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return max(0.0, min(VAD_MAX, float(v)))
COMMENT = "Ally Companion microphone noise suppression"


def internal_mic(sources: Any) -> Optional[str]:
    """The internal analog microphone; Valve's WirePlumber puts a loopback source in front of it."""
    names = [s["name"] for s in sources]
    for prefix in ("alsa_loopback_device.alsa_input.", "alsa_input."):
        for n in names:
            if n.startswith(prefix) and "analog" in n:
                return n
    return None


def config(target: str, vad: float) -> str:
    return confgen.compose(f"""  {{ name = libpipewire-module-filter-chain
    flags = [ nofail ]
    args = {{
      node.description = "Ally Companion: noise-suppressed microphone"
      media.name = "Ally Companion: noise-suppressed microphone"
      filter.graph = {{
        nodes = [
          {{ type = ladspa name = rnnoise plugin = {chains.quote(LADSPA)} label = "nt-filter"
            control = {{ "VAD %%" = {vad:.1f} }} }}
        ]
      }}
      audio.rate = 48000
      audio.position = [ FL FR ]
      capture.props = {{
        node.name = "effect_input.{NODE}"
        node.passive = true
        node.link-group = "{NODE}"
        target.object = {chains.quote(target)}
        stream.dont-remix = true
      }}
      playback.props = {{
        node.name = "effect_output.{NODE}"
        node.link-group = "{NODE}"
        media.class = "Audio/Source"
        priority.session = {PRIORITY}
      }}
    }}
  }}
""", COMMENT)



class Mic(Module):
    id = "mic"
    title = "Microphone noise suppression"
    toggle = True
    defaults = {"enabled": False, "vad": 50.0}

    def __init__(self) -> None:
        super().__init__()
        self.chain = chains.UserChain("mic", "Ally Companion microphone noise suppression")
        self._target: Optional[str] = None

    def supported(self) -> Tuple[bool, str]:
        if not os.path.exists(LADSPA):
            return False, "librnnoise_ladspa is not installed"
        return True, ""

    def normalize(self, cfg: Dict[str, Any]) -> None:
        cfg["vad"] = clean_vad(cfg.get("vad"))

    def set_options(self, opts: Dict[str, Any]) -> bool:
        if "vad" in opts:
            self.update_cfg({"vad": clean_vad(opts["vad"], float(self.cfg.get("vad", 50.0)))})
            return True
        return False

    def is_applied(self) -> bool:
        return self.chain.is_active(STATUS_AGE_S)

    async def apply(self) -> None:
        sources = await asyncio.to_thread(chains.nodes, "Audio/Source")
        target = internal_mic(sources)
        if not target:
            raise RuntimeError("internal microphone not found in PipeWire")
        self._target = target
        changed = await asyncio.to_thread(self.chain.write, config(target, clean_vad(self.cfg.get("vad"))))
        await asyncio.to_thread(lambda: self.chain.start(changed and self.chain.is_active()))
        logger.info("[mic] noise suppression on %s", target)

    async def revert(self) -> None:
        await asyncio.to_thread(self.chain.stop)

    async def uninstall(self) -> None:
        await asyncio.to_thread(self.chain.remove)

    def details(self) -> Dict[str, Any]:
        return {"vad": self.cfg.get("vad", 50.0), "target": self._target, "active": self.chain.is_active(STATUS_AGE_S),
                "verified": chains.node_present(f"effect_output.{NODE}", max_age=STATUS_AGE_S)}
