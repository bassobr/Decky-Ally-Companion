"""Headphone EQ: AutoEQ correction profiles as a PipeWire filter chain (built-in biquads).

AutoEQ (https://github.com/jaakkopasanen/AutoEq) publishes a ParametricEQ.txt per headphone model;
it is searched and fetched on demand. Wired headphones share the internal analog sink with the
speakers, so the chain runs only while the headphone route is active (the speaker DSP pauses then);
a Bluetooth or USB headset is targeted by its own sink and the chain runs while that sink exists.

A profile can only make things quieter: only paths from AutoEQ's index are fetched, filter values
are bounded, and the preamp is lowered until the summed response stays at or below 0 dB, whatever
the profile file, settings.json or a backup says. Jack events (jacksense) trigger the checks;
without them the route is polled.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from allydsp import confgen, hardware
from allydsp import paths as dsp_paths
from allydsp.util import atomic_write_text

from .. import chains, safefs
from ..constants import USER_AGENT
from ..log import logger
from ..module import Module, cancel_task
from ..util import run

AUTOEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
INDEX_MAX_AGE_S = 7 * 24 * 3600
IDLE_S = 60.0  # safety re-check while jack events drive the wired case
POLL_S = 3.0  # wired without jack events
OUTPUT_POLL_S = 5.0  # Bluetooth/USB: the sink comes and goes without a jack event
BURST_S, BURST_STEP_S = 3.0, 0.5  # after a jack event PipeWire moves the route with a delay
NODE = "ally_companion_hp"
COMMENT = "Ally Companion headphone EQ"
MAX_FILTERS = 20
GAIN_DB = (-24.0, 12.0)
Q_RANGE = (0.1, 10.0)
FREQ_HZ = (20.0, 20000.0)
MIN_PREAMP_DB = -40.0  # a profile that needs more attenuation than this is not a correction
SAMPLE_RATE = 48000
# paths contain parentheses ("1MORE Aero (ANC On)"), so the path runs up to the last ") by "
_INDEX_LINE = re.compile(r"^- \[(?P<name>[^\]]+)\]\(\./(?P<path>.+)\) by (?P<source>.+?)\s*$")
_PREAMP = re.compile(r"^Preamp:\s*(-?[\d.]+)\s*dB", re.I)
_FILTER = re.compile(r"^Filter\s+\d+:\s*ON\s+(PK|LSC|HSC|LS|HS)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+(-?[\d.]+)\s*dB(?:\s+Q\s+([\d.]+))?", re.I)
TYPES = {"PK": "bq_peaking", "LSC": "bq_lowshelf", "LS": "bq_lowshelf", "HSC": "bq_highshelf", "HS": "bq_highshelf"}
_GRID = [FREQ_HZ[0] * (FREQ_HZ[1] / FREQ_HZ[0]) ** (i / 239) for i in range(240)]  # log-spaced


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


def profile_url(path: str) -> str:
    """URL of a profile below AutoEQ's results; refuses paths that would leave them."""
    parts = path.strip("/").split("/")
    if not path or any(p in ("", ".", "..") or "\\" in p for p in parts):
        raise ValueError(f"unexpected AutoEQ path {path!r}")
    quoted = "/".join(urllib.parse.quote(p, safe="") for p in parts)
    return f"{AUTOEQ_RAW}/{quoted}/{urllib.parse.quote(parts[-1] + ' ParametricEQ.txt', safe='')}"


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


def _coeffs(kind: str, freq: float, gain: float, q: float) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """RBJ cookbook biquad, as PipeWire's builtin bq_* filters compute it."""
    a = 10 ** (gain / 40)
    w0 = 2 * math.pi * freq / SAMPLE_RATE
    cw, alpha = math.cos(w0), math.sin(w0) / (2 * q)
    if kind == "bq_peaking":
        return (1 + alpha * a, -2 * cw, 1 - alpha * a), (1 + alpha / a, -2 * cw, 1 - alpha / a)
    sa = 2 * math.sqrt(a) * alpha
    if kind == "bq_lowshelf":
        return ((a * ((a + 1) - (a - 1) * cw + sa), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - sa)),
                ((a + 1) + (a - 1) * cw + sa, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - sa))
    return ((a * ((a + 1) + (a - 1) * cw + sa), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - sa)),
            ((a + 1) - (a - 1) * cw + sa, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - sa))


def _db(c: Tuple[Tuple[float, ...], Tuple[float, ...]], freq: float) -> float:
    w = 2 * math.pi * freq / SAMPLE_RATE
    z = complex(math.cos(w), -math.sin(w))  # e^-jw; Decky's bundled Python has no cmath
    b, a = c
    h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return 20 * math.log10(max(abs(h), 1e-12))


def max_boost_db(filters: List[Dict[str, Any]]) -> float:
    """Highest level of the summed filter response, checked on a log grid and at every filter."""
    cs = [_coeffs(f["type"], f["freq"], f["gain"], f["q"]) for f in filters]
    return max(sum(_db(c, f) for c in cs) for f in _GRID + [f["freq"] for f in filters])


def _number(v: Any, lo: float, hi: float) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, x)) if math.isfinite(x) else None


def sanitize_eq(eq: Any) -> Optional[Dict[str, Any]]:
    """A profile bounded as described above; None when nothing usable is left."""
    if not isinstance(eq, dict) or not isinstance(eq.get("filters"), list):
        return None
    filters = []
    for f in eq["filters"][:MAX_FILTERS]:
        if not isinstance(f, dict) or f.get("type") not in TYPES.values():
            continue
        freq, gain, q = _number(f.get("freq"), *FREQ_HZ), _number(f.get("gain"), *GAIN_DB), _number(f.get("q", 0.707), *Q_RANGE)
        if freq is not None and gain is not None and q is not None:
            filters.append({"type": f["type"], "freq": freq, "gain": gain, "q": q})
    if not filters:
        return None
    preamp = min(_number(eq.get("preamp", 0.0), MIN_PREAMP_DB * 2, 0.0) or 0.0, -max(0.0, max_boost_db(filters)))
    if preamp < MIN_PREAMP_DB:
        return None
    rounded = round(preamp, 2)
    if rounded > preamp + 1e-9:  # round down, never up (stable when the value is checked again)
        rounded = round(rounded - 0.01, 2)
    out: Dict[str, Any] = {"preamp": rounded, "filters": filters}
    for k, n in (("name", 120), ("source", 80), ("path", 300)):
        if isinstance(eq.get(k), str):
            out[k] = eq[k][:n]
    return out


def config(eq: Dict[str, Any], target: str) -> str:
    safe = sanitize_eq(eq)
    if safe is None:
        raise ValueError("the profile has no usable filters")
    nodes = ['          { type = builtin name = preamp label = bq_highshelf control = { "Freq" = 0.0 "Q" = 1.0 "Gain" = %.2f } }'
             % safe["preamp"]]
    links = []
    prev = "preamp"
    for i, f in enumerate(safe["filters"]):
        name = f"f{i + 1}"
        nodes.append('          { type = builtin name = %s label = %s control = { "Freq" = %.1f "Q" = %.3f "Gain" = %.2f } }'
                     % (name, f["type"], f["freq"], f["q"], f["gain"]))
        links.append(f'          {{ output = "{prev}:Out" input = "{name}:In" }}')
        prev = name
    return confgen.compose(f"""  {{ name = libpipewire-module-filter-chain
    flags = [ nofail ]
    args = {{
      node.description = {chains.quote("Ally Companion EQ: " + str(safe.get("name", "")))}
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
    r = run(["curl", "-fsSL", "--max-time", str(timeout), "--max-filesize", str(4 << 20), "-A", USER_AGENT, url],
            timeout=timeout + 5)
    if not r.ok:
        raise RuntimeError(f"download failed (rc={r.rc}): {r.err.strip()[:120]}")
    return r.out


def clean_output(v: Any) -> str:
    return v if isinstance(v, str) and 0 < len(v) <= 200 else "wired"


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
        self._conf_text = ""
        self._wake: Optional[asyncio.Event] = None
        self._burst_until = 0.0

    def normalize(self, cfg: Dict[str, Any]) -> None:
        cfg["eq"] = sanitize_eq(cfg.get("eq"))
        cfg["output"] = clean_output(cfg.get("output"))

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
        out = clean_output(self.cfg.get("output"))
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
            self._task = asyncio.get_running_loop().create_task(self._watch())

    async def revert(self) -> None:
        await cancel_task(self._task)
        self._task = None
        await asyncio.to_thread(self.chain.stop)
        self._running_on = None

    async def start(self) -> None:
        if self.ctx and self.ctx.jack:
            self.ctx.jack.subscribe(self._on_jack)
        await self.reapply_if_enabled()

    async def stop(self) -> None:
        if self.ctx and self.ctx.jack:
            self.ctx.jack.unsubscribe(self._on_jack)
        await cancel_task(self._task)
        self._task = None

    async def on_resume(self, slept_s: float) -> None:
        self.kick()

    async def uninstall(self) -> None:
        await asyncio.to_thread(self.chain.remove)

    def details(self) -> Dict[str, Any]:
        eq = self.cfg.get("eq") or None
        return {"eq": {k: eq[k] for k in ("name", "source", "preamp") if k in eq} if eq else None,
                "filters": len(eq["filters"]) if eq else 0, "output": clean_output(self.cfg.get("output")),
                "running": self.chain.is_active(2.0), "runningOn": self._running_on}

    # ------------------------------------------------------------- running the chain
    def kick(self) -> None:
        """Check now and a few times right after (a jack event, a resume)."""
        self._burst_until = time.monotonic() + BURST_S
        if self._wake is not None:
            self._wake.set()

    async def _on_jack(self, inserted: bool) -> None:
        self.kick()

    def _interval(self) -> float:
        if time.monotonic() < self._burst_until:
            return BURST_STEP_S
        if not self.cfg.get("eq"):
            return IDLE_S
        if clean_output(self.cfg.get("output")) != "wired":
            return OUTPUT_POLL_S
        return IDLE_S if self.ctx and self.ctx.jack and self.ctx.jack.available else POLL_S

    async def _sync(self, force: bool = False) -> None:
        eq = self.cfg.get("eq")
        if not eq:
            if self._running_on is not None or force:
                await asyncio.to_thread(self.chain.stop)
                self._running_on = None
            return
        dump = await asyncio.to_thread(hardware.pw_dump)
        sink, run_now = self.target(dump)
        if not sink or not run_now:
            if self._running_on is not None or force:
                await asyncio.to_thread(self.chain.stop)
                self._running_on = None
            return
        text = config(eq, sink)
        changed = False
        if force or text != self._conf_text:
            changed = await asyncio.to_thread(self.chain.write, text)
            self._conf_text = text
        if changed or self._running_on != sink or not await asyncio.to_thread(self.chain.is_active, IDLE_S / 2):
            await asyncio.to_thread(self.chain.start, True)
            self._running_on = sink
            logger.info("[headphones] EQ %s on %s", eq.get("name"), sink)
            await self.notify()

    async def _watch(self) -> None:
        self._wake = asyncio.Event()
        while True:
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self._interval())
            except asyncio.TimeoutError:
                pass
            try:
                await self._sync()
            except Exception as e:  # noqa: BLE001
                logger.warning("[headphones] %s", e)

    # ------------------------------------------------------------- actions
    async def _load_index(self) -> List[Dict[str, str]]:
        path = self.index_path()
        st = await asyncio.to_thread(safefs.stat_file, path)
        fresh = st is not None and time.time() - st.st_mtime < INDEX_MAX_AGE_S
        if self._index is not None and fresh:
            return self._index
        if fresh:
            text = await asyncio.to_thread(safefs.read_text, path)
        else:
            text = await asyncio.to_thread(fetch, f"{AUTOEQ_RAW}/INDEX.md", 60)
            await asyncio.to_thread(atomic_write_text, path, text)
        self._index = parse_index(text or "")
        return self._index

    async def search(self, query: str) -> List[Dict[str, str]]:
        return search(await self._load_index(), str(query))

    async def select(self, path: str, name: str = "", source: str = "") -> None:
        """A profile from the index; name and source come from the index entry, not the caller."""
        entry = next((e for e in await self._load_index() if e["path"] == path), None)
        if entry is None:
            raise ValueError("not a headphone profile from the AutoEQ index")
        eq = sanitize_eq({**parse_parametric(await asyncio.to_thread(fetch, profile_url(entry["path"]))),
                          "name": entry["name"], "source": entry["source"], "path": entry["path"]})
        if eq is None:
            raise ValueError("the profile has no usable filters")
        self.update_cfg({"eq": eq})
        logger.info("[headphones] profile %s (%s, %d filters, preamp %.1f dB)", eq["name"], eq["source"],
                    len(eq["filters"]), eq["preamp"])
        if self.enabled:
            await self._sync(force=True)

    async def clear(self) -> None:
        self.update_cfg({"eq": None})
        await asyncio.to_thread(self.chain.stop)
        self._running_on = None

    async def set_output(self, output: str) -> None:
        self.update_cfg({"output": clean_output(output)})
        if self.enabled:
            await asyncio.to_thread(self.chain.stop)
            self._running_on = None
            await self._sync(force=True)
            self.kick()

    async def outputs(self) -> List[Dict[str, str]]:
        """Sinks a headset can be: everything but the internal one and filter nodes."""
        dump = await asyncio.to_thread(hardware.pw_dump)
        wired = self.wired_sink(dump)
        return [n for n in chains.nodes("Audio/Sink", dump)
                if n["name"] != wired and not n["name"].startswith("effect_input.")]
