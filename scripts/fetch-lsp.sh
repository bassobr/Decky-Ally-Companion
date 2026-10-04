#!/usr/bin/env bash
# Fetch lsp-plugins-lv2 from the SteamOS mirror, verify it and copy the plugins
# Ally Companion uses into bin/lv2/. Usage: scripts/fetch-lsp.sh [dest_dir]
set -euo pipefail
PKG_URL="${LSP_PKG_URL:-https://steamdeck-packages.steamos.cloud/archlinux-mirror/extra-3.8/os/x86_64/lsp-plugins-lv2-1.2.22-1-x86_64.pkg.tar.zst}"
PKG_SHA256="${LSP_PKG_SHA256:-49b37861d815241b1f08c44c8dab80cfceb389865ae5c9eaec453056743c5676}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/bin/lv2}"
KEEP=(limiter_stereo mb_compressor_stereo para_equalizer_x16_lr autogain_stereo filter_stereo)
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
CACHE="${LSP_PKG_CACHE:-$ROOT/.cache}"; mkdir -p "$CACHE"
PKG="$CACHE/$(basename "$PKG_URL")"
if [ ! -f "$PKG" ]; then
  echo "downloading $(basename "$PKG_URL")"
  curl -fL --retry 3 -o "$PKG.part" "$PKG_URL" && mv "$PKG.part" "$PKG"
fi
sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d" " -f1; else shasum -a 256 "$1" | cut -d" " -f1; fi; }
ACTUAL="$(sha256_of "$PKG")"
[ "$ACTUAL" = "$PKG_SHA256" ] || { echo "checksum mismatch for $PKG: $ACTUAL" >&2; rm -f "$PKG"; exit 1; }
if command -v zstd >/dev/null 2>&1; then zstd -dc "$PKG" | tar -xf - -C "$TMP" usr/lib/lv2/lsp-plugins.lv2
else tar --zstd -xf "$PKG" -C "$TMP" usr/lib/lv2/lsp-plugins.lv2; fi
SRC="$TMP/usr/lib/lv2/lsp-plugins.lv2"
OUT="$DEST/lsp-plugins.lv2"; rm -rf "$OUT"; mkdir -p "$OUT"
cp "$SRC/lsp-plugins-lv2.so" "$OUT/"
for k in "${KEEP[@]}"; do cp "$SRC/$k.ttl" "$OUT/"; done
python3 "$ROOT/scripts/trim-lv2-manifest.py" "$SRC/manifest.ttl" "$OUT/manifest.ttl" "${KEEP[@]}"
cp "$ROOT/third_party/licenses/LGPL-3.0.txt" "$OUT/LICENSE.LGPL-3.0.txt"
cat > "$OUT/NOTICE.txt" <<NOTICE
LSP Plugins (https://lsp-plug.in), LGPL-3.0-or-later. Unmodified binary from the
Arch Linux package lsp-plugins-lv2 1.2.22 ($PKG_URL); only the plugin descriptions
Ally Companion uses are included. Source: https://github.com/lsp-plugins/lsp-plugins
NOTICE
du -sh "$OUT" | cut -f1; ls "$OUT"
