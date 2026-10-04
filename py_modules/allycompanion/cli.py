"""Support CLI: `sudo PYTHONPATH=py_modules python3 -m allycompanion.cli diagnostics` in the plugin dir."""
from __future__ import annotations

import argparse
import json
import sys

from . import device, diagnostics


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="allycompanion.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="device and system stack as JSON")
    sub.add_parser("diagnostics", help="full diagnostics report")
    a = ap.parse_args(argv)
    if a.cmd == "info":
        print(json.dumps({"device": device.info(), "stack": device.stack()}, indent=2))
    else:
        print(diagnostics.render_text(diagnostics.collect()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
