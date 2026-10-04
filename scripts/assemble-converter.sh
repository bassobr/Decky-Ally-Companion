#!/usr/bin/env bash
# Copy the converter files the plugin needs from the submodule into defaults/converter/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/third_party/speaker-tuning-to-easyeffects"
DST="$ROOT/defaults/converter"
[ -f "$SRC/dolby_to_pipewire.py" ] || { echo "submodule missing: run git submodule update --init" >&2; exit 1; }
rm -rf "$DST"; mkdir -p "$DST"
cp "$SRC"/dolby_to_pipewire.py "$SRC"/dolby_to_easyeffects.py "$SRC"/ee_to_pipewire.py "$SRC"/LICENSE "$SRC"/README.md "$DST/"
cp -R "$SRC/lib" "$DST/lib"
find "$DST" -name "__pycache__" -type d -prune -exec rm -rf {} +
git -C "$SRC" rev-parse --short HEAD > "$DST/COMMIT" 2>/dev/null || echo unknown > "$DST/COMMIT"
echo "converter assembled at $(cat "$DST/COMMIT")"; du -sh "$DST" | cut -f1
