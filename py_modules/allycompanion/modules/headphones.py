"""Headphone EQ: AutoEQ correction profiles as a PipeWire filter chain (built-in biquads).

AutoEQ (https://github.com/jaakkopasanen/AutoEq) publishes a ParametricEQ.txt per headphone model;
it is searched and fetched on demand. Wired headphones share the internal analog sink with the
speakers, so the chain runs only while the headphone route is active (the speaker DSP pauses then);
a Bluetooth or USB headset is targeted by its own sink and the chain runs while that sink exists.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from allydsp import confgen, hardware
from allydsp import paths as dsp_paths
from allydsp.util import atomic_write_text

from .. import chains
from ..constants import USER_AGENT
from ..log import logger
from ..module import Module, cancel_task
from ..util import run

AUTOEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
INDEX_MAX_AGE_S = 7 * 24 * 3600
WATCH_S = 3.0
NODE = "ally_companion_hp"
COMMENT = "Ally Companion headphone EQ"
# paths contain parentheses ("1MORE Aero (ANC On)"), so the path runs up to the last ") by "
_INDEX_LINE = re.compile(r"^- \[(?P<name>[^\]]+)\]\(\./(?P<path>.+)\) by (?P<source>.+?)\s*$")
_PREAMP = re.compile(r"^Preamp:\s*(-?[\d.]+)\s*dB", re.I)
_FILTER = re.compile(r"^Filter\s+\d+:\s*ON\s+(PK|LSC|HSC|LS|HS)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+(-?[\d.]+)\s*dB(?:\s+Q\s+([\d.]+))?", re.I)
TYPES = {"PK": "bq_peaking", "LSC": "bq_lowshelf", "LS": "bq_lowshelf", "HSC": "bq_highshelf", "HS": "bq_highshelf"}


def parse_index(text: str) -> List[Dict[str, str]]:
    out = []
    for line in text.splitlines():
        m = _INDEX_LINE.match(line.strip())
        if m:
            out.append({"name": m.group("name"), "path": urllib.parse.unquote(m.group("path")), "source": m.group("source")})
    return out


def search(index: List[Dict[str, str]], query: str, limit: int = 30) -> List[Dict[str, str]]:
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    hits = [e for e in index if all(w in e["name"].lower() for w in words)]
    return sorted(hits, key=lambda e: (len(e["name"]), e["name"]))[:limit]


def parse_parametric(text: str) -> Dict[str, Any]:
    preamp = 0.0
    filters = []
    for line in text.splitlines():
        line = line.strip()
        m = _PREAMP.match(line)
        if m:
            preamp = float(m.group(1))
            continue
        m = _FILTER.match(line)
        if m:
            filters.append({"type": TYPES[m.group(1).upper()], "freq": float(m.group(2)), "gain": float(m.group(3)),
                            "q": float(m.group(4) or 0.707)})
    if not filters:
        raise ValueError("no filters in the profile")
    return {"preamp": preamp, "filters": filters}


def config(eq: Dict[str, Any], target: str) -> str:
    nodes = ['          { type = builtin name = preamp label = bq_highshelf control = { "Freq" = 0.0 "Q" = 1.0 "Gain" = %.2f } }'
             % float(eq.get("preamp", 0.0))]
    links = []
    prev = "preamp"
    for i, f in enumerate(eq["filters"]):
        name = f"f{i + 1}"
        nodes.append('          { type = builtin name = %s label = %s control = { "Freq" = %.1f "Q" = %.3f "Gain" = %.2f } }'
                     % (name, f["type"], f["freq"], f["q"], f["gain"]))
        links.append(f'          {{ output = "{prev}:Out" input = "{name}:In" }}')
        prev = name
    return confgen.compose(f"""  {{ name = libpipewire-module-filter-chain
    flags = [ nofail ]
    args = {{
      node.description = {chains.quote("Ally Companion EQ: " + str(eq.get("name", "")))}
      media.name = "Ally Companion headphone EQ"
      filter.graph = {{
        nodes = [
{chr(10).join(nodes)}
        ]
        links = [
{chr(10).join(links)}
        ]
      }}
      audio.position = [ FL FR ]
      capture.props = {{
        node.name = "effect_input.{NODE}"
        media.class = "Audio/Sink"
        node.link-group = "{NODE}"
        filter.smart = true
        filter.smart.name = "ally-companion-hp"
        filter.smart.target = {{ node.name = {chains.quote(target)} }}
        priority.session = -1
      }}
      playback.props = {{
        node.name = "effect_output.{NODE}"
        node.passive = true
        node.link-group = "{NODE}"
      }}
    }}
  }}
""", COMMENT)


def fetch(url: str, timeout: int = 30) -> str:
    r = run(["curl", "-fsSL", "--max-time", str(timeout), "-A", USER_AGENT, url], timeout=timeout + 5)
    if not r.ok:
        raise RuntimeError(f"download failed (rc={r.rc}): {r.err.strip()[:120]}")
    return r.out



class Headphones(Module):
    id = "headphones"
    title = "Headphone EQ"
    toggle = True
    defaults = {"enabled": False, "eq": None, "output": "wired"}

    def __init__(self) -> None:
        super().__init__()
        self.chain = chains.UserChain("hp", "Ally Companion headphone EQ")
        self._task: Optional[asyncio.Task] = None
        self._index: Optional[List[Dict[str, str]]] = None
        self._running_on: Optional[str] = None

    def actions(self):
        return {"search": self.search, "select": self.select, "clear": self.clear, "set_output": self.set_output,
                "outputs": self.outputs}

    def index_path(self) -> str:
        return os.path.join(dsp_paths.RUNTIME_DIR, "autoeq-index.md")

    # ------------------------------------------------------------- target
    def wired_sink(self, dump: List[Dict[str, Any]]) -> Optional[str]:
        sink = hardware.find_speaker_sink(dump)
        return sink["name"] if sink else None

    def target(self, dump: List[Dict[str, Any]]) -> Tuple[Optional[str], bool]:
        """(sink to filter, whether the chain should run now)."""
        out = self.cfg.get("output") or "wired"
        if out == "wired":
            sink = self.wired_sink(dump)
            return sink, bool(sink) and hardware.headphones_active(hardware.output_route(dump))
        return out, chains.node_present(out, dump)

    # ------------------------------------------------------------- module interface
    def is_applied(self) -> bool:
        return bool(self.cfg.get("eq"))

    def refine(self, state: str, message: str, details: Dict[str, Any]) -> Tuple[str, str]:
        if state != "error" and self.enabled and not self.cfg.get("eq"):
            return "not_applied", "Pick your headphones"
        if state == "applied":
            return state, "Active" if details.get("running") else "Waiting for the headphones"
        return state, message

    async def apply(self) -> None:
        await self._sync(force=True)
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._watch())

    async def revert(self) -> None:
        await cancel_task(self._task)
        self._task = None
        await asyncio.to_thread(self.chain.stop)
        self._running_on = None

    async def stop(self) -> None:
        await cancel_task(self._task)
        self._task = None

    async def uninstall(self) -> None:
        await asyncio.to_thread(self.chain.remove)

    def details(self) -> Dict[str, Any]:
        eq = self.cfg.get("eq") or None
        return {"eq": {k: eq[k] for k in ("name", "source", "preamp") if k in eq} if eq else None,
                "filters": len(eq["filters"]) if eq else 0, "output": self.cfg.get("output") or "wired",
                "running": self.chain.is_active(), "runningOn": self._running_on}

    # ------------------------------------------------------------- running the chain
    async def _sync(self, force: bool = False) -> None:
        eq = self.cfg.get("eq")
        dump = await asyncio.to_thread(hardware.pw_dump)
        sink, run_now = self.target(dump)
        if not eq or not sink or not run_now:
            if self._running_on is not None or force:
                await asyncio.to_thread(self.chain.stop)
                self._running_on = None
            return
        changed = await asyncio.to_thread(self.chain.write, config(eq, sink))
        if changed or self._running_on != sink or not await asyncio.to_thread(self.chain.is_active):
            await asyncio.to_thread(self.chain.start, True)
            self._running_on = sink
            logger.info("[headphones] EQ %s on %s", eq.get("name"), sink)
            await self.notify()

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(WATCH_S)
            try:
                await self._sync()
            except Exception as e:  # noqa: BLE001
                logger.warning("[headphones] %s", e)

    # ------------------------------------------------------------- actions
    async def _load_index(self) -> List[Dict[str, str]]:
        path = self.index_path()
        fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < INDEX_MAX_AGE_S
        if self._index is not None and fresh:
            return self._index
        if not fresh:
            text = await asyncio.to_thread(fetch, f"{AUTOEQ_RAW}/INDEX.md", 60)
            await asyncio.to_thread(atomic_write_text, path, text)
        with open(path, "r", encoding="utf-8") as f:
            self._index = parse_index(f.read())
        return self._index

    async def search(self, query: str) -> List[Dict[str, str]]:
        return search(await self._load_index(), str(query))

    async def select(self, path: str, name: str, source: str = "") -> None:
        base = os.path.basename(path.rstrip("/"))
        url = f"{AUTOEQ_RAW}/{urllib.parse.quote(path)}/{urllib.parse.quote(base + ' ParametricEQ.txt')}"
        eq = parse_parametric(await asyncio.to_thread(fetch, url))
        eq.update({"name": str(name)[:120], "source": str(source)[:80], "path": path})
        self.update_cfg({"eq": eq})
        logger.info("[headphones] profile %s (%s, %d filters)", name, source, len(eq["filters"]))
        if self.enabled:
            await self._sync(force=True)

    async def clear(self) -> None:
        self.update_cfg({"eq": None})
        await asyncio.to_thread(self.chain.stop)
        self._running_on = None

    async def set_output(self, output: str) -> None:
        self.update_cfg({"output": str(output) or "wired"})
        if self.enabled:
            await asyncio.to_thread(self.chain.stop)
            self._running_on = None
            await self._sync(force=True)

    async def outputs(self) -> List[Dict[str, str]]:
        """Sinks a headset can be: everything but the internal one and filter nodes."""
        dump = await asyncio.to_thread(hardware.pw_dump)
        wired = self.wired_sink(dump)
        return [n for n in chains.nodes("Audio/Sink", dump)
                if n["name"] != wired and not n["name"].startswith("effect_input.")]
