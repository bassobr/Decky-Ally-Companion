"""Locate, download and unpack the ASUS Dolby Atmos driver package and extract
the DAX3 tuning XML for this codec."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

from . import devices, paths
from .constants import USER_AGENT
from .log import logger
from .util import read_json, run, sha256_file, user_env, write_json

SIG_7Z = b"7z\xbc\xaf\x27\x1c"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_PACKAGE = 256 << 20
Progress = Optional[Callable[[float, str], None]]


class NoTuning(RuntimeError):
    """The package has no DAX3 XML for this codec's DEV/SUBSYS."""


def load_fallback() -> Dict[str, Any]:
    return devices.load_registry()


def device_source(ssid: str) -> Dict[str, Any]:
    dev = devices.lookup(ssid)
    if not dev:
        raise RuntimeError(f"No package source for codec subsystem {devices.normalize_ssid(ssid)} "
                           f"(known: {', '.join(devices.supported_ssids())})")
    return dev


def pinned_package(ssid: str) -> Optional[Dict[str, Any]]:
    pkg = dict(device_source(ssid).get("package") or {})
    if not pkg.get("url"):
        return None
    pkg["source"] = "fallback"
    return pkg


def _curl_json(url: str, timeout: int = 30) -> Optional[Any]:
    r = run(["curl", "-fsSL", "--max-time", str(timeout), "-A", USER_AGENT,
             "-H", "Accept: application/json", "-H", "Referer: https://www.asus.com/", url], timeout=timeout + 5)
    if not r.ok:
        logger.warning(f"ASUS API request failed rc={r.rc}: {r.err.strip()[:200]}")
        return None
    try:
        return json.loads(r.out)
    except ValueError:
        logger.warning("ASUS API returned non-JSON")
        return None


def _walk_files(obj: Any):
    if isinstance(obj, dict):
        if "DownloadUrl" in obj and "Title" in obj:
            yield obj
        for v in obj.values():
            yield from _walk_files(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_files(v)


def parse_api(data: Any, cdn: str) -> Optional[Dict[str, Any]]:
    """Pick the newest 'Dolby Atmos driver' entry from the ASUS driver JSON."""
    best = None
    for f in _walk_files(data):
        title = str(f.get("Title", ""))
        if "dolby atmos" not in title.lower():
            continue
        du = f.get("DownloadUrl")
        url = du.get("Global") if isinstance(du, dict) else du
        if not url:
            continue
        if not str(url).startswith("http"):
            url = cdn.rstrip("/") + "/" + str(url).lstrip("/")
        cand = {
            "title": title,
            "version": str(f.get("Version", "")),
            "release_date": str(f.get("ReleaseDate", "")),
            "url": url,
            "sha256": str(f.get("sha256", "")).lower() or None,
            "size_text": str(f.get("FileSize", "")),
        }
        if best is None or cand["release_date"] > best["release_date"]:
            best = cand
    return best


def all_pinned_packages() -> List[Dict[str, Any]]:
    """Every distinct pinned package in the registry; for devices without an entry (setup with 'try anyway')."""
    out: List[Dict[str, Any]] = []
    for ssid in devices.supported_ssids():
        pkg = pinned_package(ssid)
        if pkg and pkg.get("sha256") not in {p.get("sha256") for p in out}:
            out.append(pkg)
    return out


def resolve_package(ssid: str, use_network: bool = True) -> Dict[str, Any]:
    """Newest Dolby package from this device's ASUS API query, else its pinned fallback."""
    dev = device_source(ssid)
    if use_network and dev.get("asus_api"):
        data = _curl_json(dev["asus_api"])
        if data is not None:
            pick = parse_api(data, load_fallback()["asus_cdn"])
            # a package without a published checksum is never downloaded: the pin is used instead
            if pick and SHA256.match(pick.get("sha256") or "") and str(pick.get("url", "")).startswith("https://"):
                pick["source"] = "asus-api"
                return pick
            if pick:
                logger.warning("ASUS lists %s without a SHA-256; using the pinned package", pick.get("version"))
    pkg = pinned_package(ssid)
    if not pkg:
        raise RuntimeError(f"No package source available for {dev.get('name')} (API unreachable and no fallback pinned)")
    return pkg


def head_size(url: str) -> Optional[int]:
    r = run(["curl", "-sIL", "--max-time", "20", "-A", USER_AGENT, url], timeout=25)
    sizes = re.findall(r"(?i)^content-length:\s*(\d+)", r.out, re.M)
    return int(sizes[-1]) if sizes else None


def download(url: str, dest: str, expected_sha256: Optional[str] = None, expected_size: Optional[int] = None,
             progress: Progress = None, timeout: int = 1800) -> str:
    """Resumable curl download with size-based progress and SHA-256 check. Returns the digest.
    Without an expected SHA-256 nothing is downloaded."""
    if not SHA256.match((expected_sha256 or "").lower()):
        raise RuntimeError("no SHA-256 published for this package; not downloading it")
    if not url.startswith("https://"):
        raise RuntimeError(f"refusing a download that is not HTTPS: {url}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    total = expected_size or head_size(url)
    # -sS: no progress meter on stderr, which is read only after curl exits (a full pipe would stall it)
    cmd = ["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "15",
           "--max-time", str(timeout), "--max-filesize", str(MAX_PACKAGE), "-A", USER_AGENT, "-C", "-", "-o", dest, url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=user_env())
    last = -1.0
    try:
        while proc.poll() is None:
            time.sleep(0.5)
            if progress and total:
                try:
                    done = os.path.getsize(dest)
                except OSError:
                    done = 0
                pct = min(99.0, 100.0 * done / total)
                if pct - last >= 1.0:
                    last = pct
                    progress(pct, f"{done / 1e6:.1f} / {total / 1e6:.1f} MB")
    except BaseException:  # cancelled (SIGTERM, cancel check): curl must not outlive the worker
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        err = (proc.stderr.read() if proc.stderr else "").strip()[-300:]
        raise RuntimeError(f"Download failed (curl rc={proc.returncode}): {err}")
    digest = sha256_file(dest)
    if digest.lower() != (expected_sha256 or "").lower():
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise RuntimeError(f"Checksum mismatch: expected {expected_sha256}, got {digest}")
    if progress:
        progress(100.0, "verified")
    return digest


def find_7z_offset(path: str, chunk: int = 1 << 20) -> Optional[int]:
    with open(path, "rb") as f:
        pos = 0
        tail = b""
        while True:
            data = f.read(chunk)
            if not data:
                return None
            buf = tail + data
            i = buf.find(SIG_7Z)
            if i >= 0:
                return pos - len(tail) + i
            tail = buf[-(len(SIG_7Z) - 1):]
            pos += len(data)


def slice_payload(exe: str, payload: str, offset: int) -> None:
    with open(exe, "rb") as src, open(payload, "wb") as dst:
        src.seek(offset)
        shutil.copyfileobj(src, dst, 1 << 20)


def list_7z(payload: str) -> List[str]:
    r = run(["7z", "l", "-slt", "-ba", "--", payload], timeout=120)
    if not r.ok:
        raise RuntimeError(f"7z listing failed rc={r.rc}: {r.err.strip()[:200]}")
    return re.findall(r"^Path = (.+)$", r.out, re.M)


def select_paths(entries: List[str], dev: str, ssid: str) -> Dict[str, Optional[str]]:
    xml_re = re.compile(rf"(^|/)DEV_{re.escape(dev)}_SUBSYS_{re.escape(ssid)}.*\.xml$", re.I)
    inf_re = re.compile(r"(^|/)dax3_ext_rtk\.inf$", re.I)
    xml = next((e for e in entries if xml_re.search(e) and "_settings" not in e.lower()), None)
    inf = next((e for e in entries if inf_re.search(e)), None)
    return {"xml": xml, "inf": inf}


_ATTR = r'\s+value\s*=\s*"([^"]*)"'


def validate_xml(xml_path: str, ssid: str) -> Dict[str, Any]:
    """Validate the DAX3 XML with regexes; Decky's bundled Python has no xml.etree."""
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not re.search(r"<device_data[\s>]", text):
        raise RuntimeError("Unexpected XML root (no <device_data>)")
    key = re.search(r"<security-key" + _ATTR, text)
    key_val = key.group(1) if key else ""
    if f"SUBSYS_{ssid}".lower() not in key_val.lower():
        raise RuntimeError("XML security-key does not reference this device's subsystem id")
    profiles = re.findall(r'<profile\s+type\s*=\s*"([^"]+)"', text)
    endpoints = re.findall(r'<endpoint\s+type\s*=\s*"([^"]+)"', text)
    meta = {}
    for k in ("xml_version", "dtt_version", "tuning_version", "tuning_date"):
        m = re.search(rf"<{k}" + _ATTR, text)
        meta[k] = m.group(1) if m else None
    return {"profiles": profiles, "endpoints": endpoints, **meta}


def inf_mentions(inf_path: str, ssid: str) -> bool:
    try:
        with open(inf_path, "r", encoding="utf-8", errors="replace") as f:
            return f"SUBSYS_{ssid}".lower() in f.read().lower()
    except OSError:
        return False


def extract_dax3(exe_path: str, codec: Dict[str, Any], progress: Progress = None,
                 package: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dev, ssid = codec["dev"].upper(), codec["ssid"].upper()
    os.makedirs(paths.DAX3_DIR, exist_ok=True)
    work = os.path.join(paths.TMP_DIR, "extract")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    if progress:
        progress(5, "searching embedded archive")
    offset = find_7z_offset(exe_path)
    if offset is None:
        raise RuntimeError("No embedded 7z archive found in the installer")
    payload = os.path.join(work, "payload.7z")
    slice_payload(exe_path, payload, offset)
    if progress:
        progress(30, "listing archive")
    entries = list_7z(payload)
    sel = select_paths(entries, dev, ssid)
    if not sel["xml"]:
        raise NoTuning(f"Package contains no tuning for DEV_{dev}_SUBSYS_{ssid}")
    targets = [sel["xml"]] + ([sel["inf"]] if sel["inf"] else [])
    if progress:
        progress(50, "extracting")
    r = run(["7z", "e", "-y", f"-o{work}", "--", payload] + targets, timeout=300)  # "--": names are not switches
    if not r.ok:
        raise RuntimeError(f"7z extraction failed rc={r.rc}: {r.err.strip()[:200]}")
    xml_name = os.path.basename(sel["xml"])
    xml_src = os.path.join(work, xml_name)
    if not os.path.exists(xml_src):
        raise RuntimeError("Extraction produced no XML")
    info = validate_xml(xml_src, ssid)
    xml_dst = os.path.join(paths.DAX3_DIR, xml_name)
    shutil.copy2(xml_src, xml_dst)
    inf_dst = None
    if sel["inf"]:
        inf_src = os.path.join(work, os.path.basename(sel["inf"]))
        if os.path.exists(inf_src):
            inf_dst = os.path.join(paths.DAX3_DIR, os.path.basename(sel["inf"]))
            shutil.copy2(inf_src, inf_dst)
    prov = {
        "xml_name": xml_name,
        "xml_sha256": sha256_file(xml_dst),
        "inf_name": os.path.basename(inf_dst) if inf_dst else None,
        "inf_mentions_ssid": inf_mentions(inf_dst, ssid) if inf_dst else None,
        "codec": codec,
        "package": package or {},
        "archive_offset": offset,
        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "xml_info": info,
        "method": "asus-package",
    }
    write_json(paths.PROVENANCE_FILE, prov)
    shutil.rmtree(work, ignore_errors=True)
    if progress:
        progress(100, xml_name)
    return prov


def provenance() -> Optional[Dict[str, Any]]:
    return read_json(paths.PROVENANCE_FILE)


def current_xml() -> Optional[str]:
    prov = provenance()
    if not prov:
        return None
    p = os.path.join(paths.DAX3_DIR, prov.get("xml_name", ""))
    return p if os.path.isfile(p) else None
