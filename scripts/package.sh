#!/usr/bin/env bash
# Build out/ally-companion-<version>.zip in the Decky layout ("Ally Companion/...").
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
NAME="Ally Companion"
VERSION="$(python3 -c "import json;print(json.load(open('package.json'))['version'])")"
[ -f dist/index.js ] || { echo "dist/index.js missing: run pnpm build" >&2; exit 1; }
[ -d bin/lv2/lsp-plugins.lv2 ] || scripts/fetch-lsp.sh
[ -f defaults/converter/dolby_to_pipewire.py ] || scripts/assemble-converter.sh
rm -rf out; mkdir -p "out/$NAME/dist"
cp plugin.json package.json main.py decky.pyi LICENSE THIRD_PARTY_LICENSES.md README.md minisign.pub "out/$NAME/"
cp dist/index.js "out/$NAME/dist/"; cp dist/index.js.map "out/$NAME/dist/" 2>/dev/null || true
cp -R py_modules bin defaults "out/$NAME/"
find "out/$NAME" -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd out && COPYFILE_DISABLE=1 zip -qr "ally-companion-$VERSION.zip" "$NAME" -x "*/._*" "*/.DS_Store")
(cd out && (sha256sum "ally-companion-$VERSION.zip" 2>/dev/null || shasum -a 256 "ally-companion-$VERSION.zip") > SHA256SUMS)
echo "built out/ally-companion-$VERSION.zip ($(du -h "out/ally-companion-$VERSION.zip" | cut -f1))"; cat out/SHA256SUMS
