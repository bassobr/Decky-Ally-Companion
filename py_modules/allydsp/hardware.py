"""Read-only probes: codec, DMI, PipeWire graph, TAS2781 controls, LV2 plugins."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from . import devices, paths
from .constants import CALF_SATURATOR_URI, INPUT_NODE, LSP_URIS
from .util import run, which

REALTEK = "10ec"


def parse_codec_header(head: str) -> Optional[Dict[str, str]]:
    codec = re.search(r"^Codec:\s*(.+)$", head, re.M)
    vendor = re.search(r"^Vendor Id:\s*0x([0-9a-fA-F]{8})", head, re.M)
    subsys = re.search(r"^Subsystem Id:\s*0x([0-9a-fA-F]{8})", head, re.M)
    if not (codec and vendor and subsys):
        return None
    return {"codec": codec.group(1).strip(), "vendor_id": vendor.group(1).lower(), "ssid": subsys.group(1).lower()}


def _codec_files() -> List[str]:
    out: List[str] = []
    base = "/proc/asound"
    try:
        cards = [c for c in os.listdir(base) if re.fullmatch(r"card\d+", c)]
    except OSError:
        return out
    for c in sorted(cards, key=lambda x: int(x[4:])):
        d = os.path.join(base, c)
        try:
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith("codec#")]
        except OSError:
            continue
    return out


def codec_info() -> Optional[Dict[str, Any]]:
    """Return the Realtek HDA codec (vendor 0x10ec) with its subsystem id."""
    for path in _codec_files():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
        except OSError:
            continue
        parsed = parse_codec_header(head)
        if not parsed or not parsed["vendor_id"].startswith(REALTEK):
            continue
        vid = parsed["vendor_id"]
        codec_name = parsed["codec"]
        card_dir = os.path.dirname(path)
        card = int(re.search(r"card(\d+)", card_dir).group(1))
        try:
            with open(os.path.join(card_dir, "id"), "r", encoding="utf-8") as f:
                card_id = f.read().strip()
        except OSError:
            card_id = str(card)
        ssid = devices.normalize_ssid(parsed["ssid"])
        dev = devices.lookup(ssid)
        return {
            "card": card,
            "card_id": card_id,
            "codec": codec_name,
            "vendor_id": vid,
            "dev": vid[4:],
            "ssid": ssid,
            "supported": dev is not None,
            "model": dev.get("name") if dev else None,
        }
    return None


def dmi() -> Dict[str, str]:
    out = {}
    for key in ("sys_vendor", "product_name", "board_name", "bios_version"):
        try:
            with open(f"/sys/devices/virtual/dmi/id/{key}", "r", encoding="utf-8") as f:
                out[key] = f.read().strip()
        except OSError:
            out[key] = ""
    return out


def kernel() -> str:
    try:
        return os.uname().release
    except Exception:
        return ""


def pw_dump() -> List[Dict[str, Any]]:
    r = run(["pw-dump"], timeout=15)
    if not r.ok:
        return []
    try:
        data = json.loads(r.out)
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def _props(obj: Dict[str, Any]) -> Dict[str, Any]:
    return obj.get("info", {}).get("props", {}) or {}


def find_speaker_sink(dump: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Internal analog sink shared by speakers and the 3.5 mm jack."""
    for obj in dump:
        p = _props(obj)
        name = str(p.get("node.name", ""))
        if p.get("media.class") == "Audio/Sink" and name.startswith("alsa_output.pci-") \
                and name.endswith("analog-stereo"):
            return {"id": obj.get("id"), "name": name, "description": p.get("node.description", ""),
                    "card_name": p.get("alsa.card_name", "")}
    return None


def output_route(dump: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Active output route of the internal analog card: speaker or headphones."""
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Device":
            continue
        p = _props(obj)
        if p.get("device.api") != "alsa" or not str(p.get("device.name", "")).startswith("alsa_card.pci-"):
            continue
        params = obj.get("info", {}).get("params", {}) or {}
        enum_names = [r.get("name", "") for r in params.get("EnumRoute", []) or []]
        if not any("analog-output" in n for n in enum_names):
            continue
        for r in params.get("Route", []) or []:
            if r.get("direction") == "Output":
                return {"name": r.get("name", ""), "description": r.get("description", ""),
                        "available": r.get("available", "unknown"), "device": p.get("device.name", "")}
    return None


def headphones_active(route: Optional[Dict[str, Any]]) -> bool:
    return bool(route) and "headphone" in str(route.get("name", "")).lower()


def filter_node_present(dump: List[Dict[str, Any]], node_name: str = INPUT_NODE) -> bool:
    return any(_props(o).get("node.name") == node_name for o in dump)


def filter_links(dump: List[Dict[str, Any]]) -> Dict[str, int]:
    """Link counts on the chain's input and output nodes."""
    ids = {o.get("id"): _props(o).get("node.name") for o in dump if _props(o).get("node.name", "").startswith("effect_")}
    counts = {"input": 0, "output": 0}
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Link":
            continue
        info = obj.get("info", {})
        if ids.get(info.get("input-node-id")) == INPUT_NODE:
            counts["input"] += 1
        if ids.get(info.get("output-node-id")) == INPUT_NODE.replace("effect_input", "effect_output"):
            counts["output"] += 1
    return counts


def tas_controls(card: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"bound": False, "controls": {}}
    r = run(["amixer", "-c", str(card), "controls"], timeout=10)
    if not r.ok:
        return out
    names = re.findall(r"name='(Speaker [^']+)'", r.out)
    out["bound"] = any(n in ("Speaker Program Id", "Speaker Config Id") for n in names)
    for n in ("Speaker Program Id", "Speaker Config Id", "Speaker Profile Id", "Speaker Analog Gain",
              "Speaker Force Firmware Load"):
        if n in names:
            c = run(["amixer", "-c", str(card), "cget", f"iface=CARD,name={n}"], timeout=10)
            m = re.search(r": values=([^\n]+)", c.out)
            out["controls"][n] = m.group(1).strip() if m else "?"
    return out


LV2_PLUGIN = "http://lv2plug.in/ns/lv2core#Plugin"
LV2_BINARY = "http://lv2plug.in/ns/lv2core#binary"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
SYSTEM_LV2_DIR = "/usr/lib/lv2"


def _ttl_statements(text: str) -> List[List[str]]:
    """Tokens per statement of a Turtle file: enough for LV2 manifests (prefixes, IRIs, prefixed
    names, `;` and `,` lists, comments), not a full parser."""
    statements: List[List[str]] = []
    tokens: List[str] = []
    tok = ""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "<":
            j = text.find(">", i)
            j = n - 1 if j < 0 else j
            tok += text[i:j + 1]
            i = j + 1
            continue
        if c == '"':
            j = text.find('"', i + 1)
            j = n - 1 if j < 0 else j
            tok += text[i:j + 1]
            i = j + 1
            continue
        if c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in ";,":
            if tok:
                tokens.append(tok)
            tokens.append(c)
            tok = ""
        elif c == "." and (i + 1 >= n or text[i + 1].isspace()):
            if tok:
                tokens.append(tok)
            if tokens:
                statements.append(tokens)
            tokens, tok = [], ""
        elif c.isspace():
            if tok:
                tokens.append(tok)
            tok = ""
        else:
            tok += c
        i += 1
    if tok:
        tokens.append(tok)
    if tokens:
        statements.append(tokens)
    return statements


def manifest_plugins(text: str, bundle: str) -> Dict[str, Optional[str]]:
    """Plugin URI -> path of its binary (None if the manifest names none) from one manifest.ttl."""
    prefixes: Dict[str, str] = {}

    def expand(term: str) -> str:
        if term.startswith("<") and term.endswith(">"):
            iri = term[1:-1]
            return iri if "://" in iri or iri.startswith("/") else os.path.join(bundle, iri)
        if ":" in term:
            p, local = term.split(":", 1)
            if p in prefixes:
                return prefixes[p] + local
        return term

    out: Dict[str, Optional[str]] = {}
    for st in _ttl_statements(text):
        if st[0].lower() in ("@prefix", "prefix") and len(st) >= 3:
            prefixes[st[1].rstrip(":")] = st[2].strip("<>")
            continue
        subject, preds, cur = expand(st[0]), {}, None
        for t in st[1:]:
            if t == ";":
                cur = None
            elif t == ",":
                continue
            elif cur is None:
                cur = RDF_TYPE if t == "a" else expand(t)
            else:
                preds.setdefault(cur, []).append(expand(t))
        if LV2_PLUGIN in preds.get(RDF_TYPE, []):
            binary = preds.get(LV2_BINARY, [None])[0]
            out[subject] = binary
    return out


def installed_lv2_plugins(dirs: List[str]) -> Dict[str, Optional[str]]:
    """Plugins declared in the manifests of every bundle in `dirs` (SteamOS 3.9 ships lilv without
    lv2ls, so the manifests are read directly)."""
    found: Dict[str, Optional[str]] = {}
    for d in dirs:
        try:
            bundles = sorted(os.listdir(d))
        except OSError:
            continue
        for b in bundles:
            bundle = os.path.join(d, b)
            try:
                with open(os.path.join(bundle, "manifest.ttl"), "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            for uri, binary in manifest_plugins(text, bundle).items():
                found.setdefault(uri, binary)
    return found


def lv2_check(lv2_dir: str = paths.LV2_DIR) -> Dict[str, Any]:
    plugins = installed_lv2_plugins([lv2_dir, SYSTEM_LV2_DIR])
    present = {u for u, binary in plugins.items() if binary is None or os.path.isfile(binary)}
    missing = [u for u in LSP_URIS if u not in present]
    return {"ok": not missing, "missing": missing, "lv2_dir": lv2_dir,
            "bundle_present": os.path.isdir(os.path.join(lv2_dir, "lsp-plugins.lv2")),
            "calf": CALF_SATURATOR_URI in present}


def tools() -> Dict[str, Optional[str]]:
    return {t: which(t) for t in ("pw-dump", "pw-cli", "wpctl", "systemctl", "journalctl", "7z", "curl",
                                  "lv2ls", "lv2info", "amixer", "pipewire")}


def summary() -> Dict[str, Any]:
    dump = pw_dump()
    codec = codec_info()
    sink = find_speaker_sink(dump)
    route = output_route(dump)
    return {
        "codec": codec,
        "dmi": dmi(),
        "kernel": kernel(),
        "sink": sink,
        "route": route,
        "headphones": headphones_active(route),
        "filter_present": filter_node_present(dump),
        "tools": tools(),
        "system_python": paths.SYSTEM_PYTHON if os.path.exists(paths.SYSTEM_PYTHON) else None,
    }
