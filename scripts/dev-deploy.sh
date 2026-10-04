#!/usr/bin/env bash
# Build, copy to the handheld and restart Decky Loader.
# Usage: scripts/dev-deploy.sh deck@<host>
# Key auth required. sudo uses DECK_SUDO_PASS from the environment if set (never stored), else sudo -n.
set -euo pipefail
HOST="${1:?usage: dev-deploy.sh user@host}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
NAME="Ally Companion"
export PATH="/opt/homebrew/bin:$PATH"
pnpm build >/dev/null
rm -rf out/deploy; mkdir -p "out/deploy/$NAME/dist"
cp plugin.json package.json main.py decky.pyi LICENSE THIRD_PARTY_LICENSES.md README.md minisign.pub "out/deploy/$NAME/"
cp dist/index.js "out/deploy/$NAME/dist/"
cp -R py_modules "out/deploy/$NAME/py_modules"
find "out/deploy/$NAME" -name "__pycache__" -type d -prune -exec rm -rf {} +
ssh "$HOST" 'rm -rf /tmp/ally-companion-deploy && mkdir -p /tmp/ally-companion-deploy'
COPYFILE_DISABLE=1 tar --no-xattrs -C out/deploy --exclude "._*" --exclude ".DS_Store" -cf - "$NAME" | ssh "$HOST" 'tar -C /tmp/ally-companion-deploy -xf -'
INSTALL='set -e; D="$HOME/homebrew/plugins/Ally Companion"; $S rm -rf "$D"; $S mv "/tmp/ally-companion-deploy/Ally Companion" "$D"; $S chown -R root:root "$D"; $S systemctl restart plugin_loader; echo "deployed, plugin_loader restarted"'
if [ -n "${DECK_SUDO_PASS:-}" ]; then
  # The password goes over the ssh channel to sudo -S once per call and is cached for the session.
  printf '%s\n' "$DECK_SUDO_PASS" | ssh "$HOST" "sudo -S -p '' -v && S='sudo -n' && $INSTALL"
else
  ssh "$HOST" "S='sudo -n'; $INSTALL"
fi
