#!/usr/bin/env bash
# Ally Companion installer: downloads the latest release, verifies checksum and
# signature, installs into ~/homebrew/plugins/Ally Companion.
#   curl -sL https://github.com/bassobr/Decky-Ally-Companion/raw/main/install.sh -o /tmp/ally-companion-install.sh && sudo bash /tmp/ally-companion-install.sh
set -euo pipefail
PLUGIN_NAME="Ally Companion"
REPO="bassobr/Decky-Ally-Companion"
# Release signing key, pinned here: the key and the verifier must not come from the zip they check.
PUBKEY="untrusted comment: Ally Companion release signing key
RWS38f5YBF9P5ORYDqf+/da56swXeggKz5y887jgbzyEA7OZvTB1o1DF"
RAW="https://raw.githubusercontent.com/$REPO/main/py_modules/allycompanion"
if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo bash $0" >&2; exit 1
fi
DECK_USER="${SUDO_USER:-$(logname 2>/dev/null || echo deck)}"
USER_HOME="$(getent passwd "$DECK_USER" | cut -d: -f6)"; USER_HOME="${USER_HOME:-/home/$DECK_USER}"
PLUGIN_BASE="$USER_HOME/homebrew/plugins"
[ -d "$PLUGIN_BASE" ] || { echo "Decky Loader not found at $PLUGIN_BASE. Install it first: https://decky.xyz" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Looking up the latest release..."
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"
[ -n "$TAG" ] || { echo "Could not determine the latest release" >&2; exit 1; }
VERSION="${TAG#v}"; ZIP="ally-companion-$VERSION.zip"; BASE="https://github.com/$REPO/releases/download/$TAG"
echo "Downloading $ZIP ($TAG)..."
curl -fsSL -o "$TMP/$ZIP" "$BASE/$ZIP"
curl -fsSL -o "$TMP/SHA256SUMS" "$BASE/SHA256SUMS"
curl -fsSL -o "$TMP/SHA256SUMS.minisig" "$BASE/SHA256SUMS.minisig"
mkdir -p "$TMP/verify/allycompanion"
for f in __init__.py ed25519.py minisign.py log.py; do curl -fsSL -o "$TMP/verify/allycompanion/$f" "$RAW/$f"; done
printf '%s\n' "$PUBKEY" > "$TMP/minisign.pub"
echo "Checking the signature..."
if PYTHONPATH="$TMP/verify" python3 -m allycompanion.minisign verify "$TMP/SHA256SUMS" "$TMP/SHA256SUMS.minisig" "$TMP/minisign.pub"; then
  echo "Signature OK."
else
  echo "Release signature INVALID, aborting." >&2; exit 1
fi
EXPECTED="$(grep " \*\?$ZIP\$" "$TMP/SHA256SUMS" | head -1 | cut -d' ' -f1)"
ACTUAL="$(sha256sum "$TMP/$ZIP" | cut -d' ' -f1)"
[ -n "$EXPECTED" ] && [ "$EXPECTED" = "$ACTUAL" ] || { echo "Checksum mismatch for $ZIP" >&2; exit 1; }
echo "Checksum OK. Extracting..."
mkdir -p "$TMP/x"
if command -v bsdtar >/dev/null 2>&1; then bsdtar -xf "$TMP/$ZIP" -C "$TMP/x"; else python3 -c "import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$TMP/$ZIP" "$TMP/x"; fi
[ -f "$TMP/x/$PLUGIN_NAME/plugin.json" ] || { echo "Unexpected zip layout" >&2; exit 1; }
cmp -s "$TMP/minisign.pub" "$TMP/x/$PLUGIN_NAME/minisign.pub" || { echo "The release carries a different signing key, aborting." >&2; exit 1; }
rm -rf "$PLUGIN_BASE/$PLUGIN_NAME"
mv "$TMP/x/$PLUGIN_NAME" "$PLUGIN_BASE/$PLUGIN_NAME"
chown -R root:root "$PLUGIN_BASE/$PLUGIN_NAME"
systemctl restart plugin_loader 2>/dev/null || true
echo "Installed $PLUGIN_NAME $VERSION. Open the Quick Access menu, Decky tab, Ally Companion."
