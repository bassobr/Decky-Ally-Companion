"""Run speaker-tuning-to-easyeffects in a private venv and write one preset
directory per Dolby profile and voicing."""
from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import confgen, paths
from .constants import PROFILE_IDS, PROFILE_LABELS, VOICING_LABELS, VOICINGS
from .log import logger
from .util import atomic_copy, atomic_write_text, read_json, run, sha256_file, user_env, write_json

Progress = Optional[Callable[[float, str], None]]
VENV_META = os.path.join(paths.VENV_DIR, "meta.json")


def venv_python() -> str:
    return os.path.join(paths.VENV_DIR, "bin", "python")


_py_version: Tuple[Optional[Tuple[int, int, int]], Optional[str]] = (None, None)
_py_lock = threading.Lock()


def system_python_version() -> Optional[str]:
    """Version of the system Python, asked once per interpreter file (status checks call this)."""
    global _py_version
    try:
        st = os.stat(paths.SYSTEM_PYTHON)
        key: Optional[Tuple[int, int, int]] = (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    with _py_lock:
        if key is not None and _py_version[0] == key:
            return _py_version[1]
    r = run([paths.SYSTEM_PYTHON, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"], timeout=20)
    version = r.out.strip() if r.ok else None
    if version and key is not None:
        with _py_lock:
            _py_version = (key, version)
    return version


def venv_meta() -> Optional[Dict[str, Any]]:
    return read_json(VENV_META)


def venv_ok() -> bool:
    meta = venv_meta()
    if not meta or not os.path.exists(venv_python()):
        return False
    return meta.get("python") == system_python_version() and bool(meta.get("import_ok"))


def ensure_venv(progress: Progress = None) -> Dict[str, Any]:
    if venv_ok():
        if progress:
            progress(100, "venv ready")
        return venv_meta() or {}
    shutil.rmtree(paths.VENV_DIR, ignore_errors=True)
    if progress:
        progress(5, "creating venv")
    r = run([paths.SYSTEM_PYTHON, "-m", "venv", paths.VENV_DIR], timeout=600)
    if not r.ok:
        raise RuntimeError(f"venv creation failed rc={r.rc}: {(r.err or r.out).strip()[-300:]}")
    if progress:
        progress(15, "installing numpy/scipy (pinned)")
    # Wheels only, each checked against the hashes in the requirements file. No unpinned fallback:
    # what runs as the user here should be exactly what was reviewed.
    pip = [venv_python(), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet",
           "--require-hashes", "--only-binary=:all:"]
    r = run(pip + ["-r", paths.CONVERTER_REQUIREMENTS], timeout=1800)
    if not r.ok:
        raise RuntimeError(f"pinned numpy/scipy install failed rc={r.rc} (no wheel for Python "
                           f"{system_python_version()}? the plugin needs new pins): {(r.err or r.out).strip()[-300:]}")
    if progress:
        progress(90, "verifying imports")
    chk = run([venv_python(), "-c", "import numpy,scipy;print(numpy.__version__);print(scipy.__version__)"], timeout=120)
    if not chk.ok:
        raise RuntimeError(f"numpy/scipy import failed: {chk.err.strip()[-300:]}")
    np_v, sp_v = (chk.out.split() + ["?", "?"])[:2]
    meta = {"python": system_python_version(), "numpy": np_v, "scipy": sp_v, "import_ok": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_json(VENV_META, meta)
    if progress:
        progress(100, f"numpy {np_v}, scipy {sp_v}")
    return meta


def converter_ok() -> bool:
    return os.path.isfile(os.path.join(paths.CONVERTER_DIR, "dolby_to_pipewire.py"))


def converter_version() -> Optional[str]:
    if not converter_ok():
        return None
    try:
        with open(os.path.join(paths.CONVERTER_DIR, "COMMIT"), "r", encoding="utf-8") as f:
            return f.read().strip()[:40] or None
    except OSError:
        return None


def extras_flags(extras: Dict[str, Any], allow_virtual_bass: bool = False) -> List[str]:
    flags: List[str] = []
    if extras.get("autogain", True):
        flags += ["--enable", "autogain"]
    if not extras.get("dialog", True):
        flags += ["--disable", "dialog"]
    if not extras.get("regulator", True):
        flags += ["--disable", "regulator"]
    if extras.get("virtualBass", False) and allow_virtual_bass:
        flags += ["--enable", "virtual-bass"]
    return flags


def preset_dir(profile: str, voicing: str) -> str:
    return os.path.join(paths.PRESETS_DIR, profile, voicing)


def preset_meta(profile: str, voicing: str) -> Optional[Dict[str, Any]]:
    return read_json(os.path.join(preset_dir(profile, voicing), "meta.json"))


def preset_available(profile: str, voicing: str) -> bool:
    d = preset_dir(profile, voicing)
    return os.path.isfile(os.path.join(d, "chain.conf")) and os.path.isfile(os.path.join(d, "ir.irs"))


def list_presets() -> Dict[str, Dict[str, bool]]:
    return {p: {v: preset_available(p, v) for v in VOICINGS} for p in PROFILE_IDS}


def description_for(profile: str, voicing: str) -> str:
    return f"Ally Companion: {PROFILE_LABELS.get(profile, profile)} ({VOICING_LABELS.get(voicing, voicing)})"


def convert_one(xml: str, profile: str, voicing: str, target_sink: str, extras: Dict[str, Any],
                xml_sha256: Optional[str] = None, allow_virtual_bass: bool = False) -> Dict[str, Any]:
    if not converter_ok():
        raise RuntimeError("converter missing (defaults/converter)")
    if not os.path.exists(venv_python()):
        raise RuntimeError("venv missing")
    tmp = os.path.join(paths.TMP_DIR, f"conv_{profile}_{voicing}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    cmd = [venv_python(), os.path.join(paths.CONVERTER_DIR, "dolby_to_pipewire.py"), xml,
           "--profile", profile, "--variant", voicing, "--target-sink", target_sink,
           "--prefix", f"allycompanion_{profile}", "--output-dir", tmp, "--no-activate", "--force", "--no-color",
           *extras_flags(extras, allow_virtual_bass)]
    env = user_env({"LV2_PATH": f"{paths.LV2_DIR}:/usr/lib/lv2", "PYTHONDONTWRITEBYTECODE": "1"})
    r = run(cmd, timeout=900, env=env, cwd=paths.CONVERTER_DIR)
    if not r.ok:
        tail = (r.err or r.out).strip().splitlines()[-6:]
        raise RuntimeError(f"converter failed for {profile}/{voicing} rc={r.rc}: " + " | ".join(tail))
    produced = sorted(os.listdir(tmp))
    confs = [os.path.join(tmp, f) for f in produced if f.endswith(".conf")]
    irss = [os.path.join(tmp, f) for f in produced if f.endswith(".irs")]
    if len(confs) != 1 or len(irss) < 1:
        raise RuntimeError(f"unexpected converter output for {profile}/{voicing}: {os.listdir(tmp)}")
    with open(confs[0], "r", encoding="utf-8") as f:
        raw = f.read()
    out_dir = preset_dir(profile, voicing)
    os.makedirs(out_dir, exist_ok=True)
    active_irs = os.path.join(paths.ACTIVE_DIR, "ir.irs")
    description = description_for(profile, voicing)
    comment = (f"preset={profile}/{voicing} target={target_sink} extras={extras_flags(extras, allow_virtual_bass)} "
               f"xml_sha256={xml_sha256 or '?'} generated={time.strftime('%Y-%m-%dT%H:%M:%S')}")
    final = confgen.finalize(raw, active_irs, description, target_sink, comment)
    # each file replaced in one step: a cancelled setup (SIGTERM) never leaves a cut-off preset behind
    atomic_copy(irss[0], os.path.join(out_dir, "ir.irs"))
    atomic_write_text(os.path.join(out_dir, "chain.conf"), final)
    atomic_write_text(os.path.join(out_dir, "converter.conf"), raw)
    meta = {
        "profile": profile, "voicing": voicing, "label": PROFILE_LABELS.get(profile, profile),
        "voicing_label": VOICING_LABELS.get(voicing, voicing), "description": description,
        "target_sink": target_sink, "extras": {k: extras.get(k) for k in ("autogain", "dialog", "regulator", "virtualBass")},
        "xml_sha256": xml_sha256, "irs_sha256": sha256_file(os.path.join(out_dir, "ir.irs")),
        "limiter_input_gain": confgen.limiter_input_gain(final),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(os.path.join(out_dir, "meta.json"), meta)
    shutil.rmtree(tmp, ignore_errors=True)
    return meta


def convert_all(xml: str, target_sink: str, extras: Dict[str, Any], progress: Progress = None,
                profiles: Optional[List[str]] = None, voicings: Optional[List[str]] = None,
                cancel: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    profiles = profiles or PROFILE_IDS
    voicings = voicings or VOICINGS
    xml_sha = sha256_file(xml)
    from .hardware import lv2_check
    allow_vb = bool(lv2_check().get("calf"))
    combos = [(p, v) for p in profiles for v in voicings]
    results: Dict[str, Any] = {}
    for i, (p, v) in enumerate(combos):
        if cancel and cancel():
            raise RuntimeError("cancelled")
        if progress:
            progress(100.0 * i / len(combos), f"{PROFILE_LABELS.get(p, p)} / {VOICING_LABELS.get(v, v)}")
        try:
            convert_one(xml, p, v, target_sink, extras, xml_sha, allow_vb)
            results[f"{p}/{v}"] = "ok"
        except Exception as e:
            logger.error(f"convert {p}/{v}: {e}")
            results[f"{p}/{v}"] = f"error: {e}"
    for name in os.listdir(paths.PRESETS_DIR) if os.path.isdir(paths.PRESETS_DIR) else []:
        if name not in PROFILE_IDS:
            shutil.rmtree(os.path.join(paths.PRESETS_DIR, name), ignore_errors=True)
    failed = [r for r in results.values() if r != "ok"]
    if failed and len(failed) == len(results):  # nothing new: the caller must not record these extras
        raise RuntimeError("All conversions failed: " + failed[0])
    if progress:
        progress(100.0, "done")
    return results
