"""Worker for everything the audio module writes; runs as the Decky user with the system Python.

    python3 -m allydsp.worker setup [--force] [--allow-unsupported] [--no-activate]
    python3 -m allydsp.worker convert | apply PROFILE VOICING [--pregain DB] [--no-start]
    python3 -m allydsp.worker enable | disable | start | stop | remove | import-legacy

Output is JSON lines: {"type": "progress", ...} while working, then one {"type": "result", "data": ...}
or {"type": "error", "error": ...}. The root backend starts it (allycompanion.modules.audio) so that
the downloads, the venv, the presets and the systemd unit belong to the user, as in Ally DSP.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
from typing import Any, Dict

from . import asus_fetch, convert, dsp_runtime, hardware, paths, settings, setup_flow


def emit(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def progress(ev: Dict[str, Any]) -> None:
    emit({"type": "progress", **ev})


def cmd_setup(a) -> Any:
    res = setup_flow.run_setup(progress, force=a.force, allow_unsupported=a.allow_unsupported, activate=not a.no_activate)
    return {k: res.get(k) for k in ("codec", "sink", "package", "results")}


def cmd_convert(a) -> Any:
    xml = asus_fetch.current_xml()
    if not xml:
        raise RuntimeError("no tuning XML present; run the setup first")
    sink = hardware.find_speaker_sink(hardware.pw_dump())
    if not sink:
        raise RuntimeError("no speaker sink found")
    st = settings.load()
    results = convert.convert_all(xml, sink["name"], st["extras"],
                                  progress=lambda pct, msg: progress({"step": "convert", "percent": round(pct, 1), "message": msg}))
    settings.update_section("setup", {"extrasSignature": settings.extras_signature(st["extras"])})
    return results


def cmd_apply(a) -> Any:
    return dsp_runtime.apply_preset(a.profile, a.voicing, a.pregain, restart_unit=not a.no_start)


def cmd_enable(a) -> Any:
    dsp_runtime.ensure_unit()
    dsp_runtime.enable(True)
    return {"enabled": True}


def cmd_disable(a) -> Any:
    dsp_runtime.stop()
    dsp_runtime.enable(False)
    return {"enabled": False}


def cmd_start(a) -> Any:
    dsp_runtime.ensure_unit()
    return {"started": dsp_runtime.start(), "verified": dsp_runtime.verify()}


def cmd_stop(a) -> Any:
    return {"stopped": dsp_runtime.stop()}


def cmd_remove(a) -> Any:
    dsp_runtime.remove_unit()
    for d in (paths.PRESETS_DIR, paths.VENV_DIR, paths.DAX3_DIR, paths.TMP_DIR):
        shutil.rmtree(d, ignore_errors=True)
    return {"removed": True}


def cmd_import_legacy(a) -> Any:
    """Copy the tuning and the converter venv of Ally DSP, so setup skips the downloads.
    The presets are converted again: their configs point at Ally DSP's directories."""
    done = []
    old = paths.LEGACY_RUNTIME_DIR
    if not asus_fetch.current_xml() and os.path.isfile(os.path.join(old, "dax3", "provenance.json")):
        shutil.rmtree(paths.DAX3_DIR, ignore_errors=True)
        shutil.copytree(os.path.join(old, "dax3"), paths.DAX3_DIR)
        done.append("dax3")
    if not convert.venv_ok() and os.path.isfile(os.path.join(old, "venv", "meta.json")):
        shutil.rmtree(paths.VENV_DIR, ignore_errors=True)
        # bin/python is a symlink to the system interpreter, so the copied venv keeps working
        shutil.copytree(os.path.join(old, "venv"), paths.VENV_DIR, symlinks=True)
        if not convert.venv_ok():
            shutil.rmtree(paths.VENV_DIR, ignore_errors=True)
        else:
            done.append("venv")
    return {"imported": done}


def _on_term(signum, frame):
    raise setup_flow.Cancelled("cancelled")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="allydsp.worker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--force", action="store_true")
    s.add_argument("--allow-unsupported", action="store_true")
    s.add_argument("--no-activate", action="store_true")
    s.set_defaults(fn=cmd_setup)
    sub.add_parser("convert").set_defaults(fn=cmd_convert)
    s = sub.add_parser("apply")
    s.add_argument("profile")
    s.add_argument("voicing")
    s.add_argument("--pregain", type=float, default=0.0)
    s.add_argument("--no-start", action="store_true")
    s.set_defaults(fn=cmd_apply)
    for name, fn in (("enable", cmd_enable), ("disable", cmd_disable), ("start", cmd_start), ("stop", cmd_stop),
                     ("remove", cmd_remove), ("import-legacy", cmd_import_legacy)):
        sub.add_parser(name).set_defaults(fn=fn)
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, _on_term)
    try:
        paths.ensure_dirs()
        emit({"type": "result", "data": a.fn(a)})
        return 0
    except setup_flow.Cancelled as e:
        emit({"type": "error", "error": str(e), "cancelled": True})
        return 2
    except Exception as e:  # noqa: BLE001
        emit({"type": "error", "error": str(e)})
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
