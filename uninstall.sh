#!/usr/bin/env bash
#
# Uninstaller: removes the auto-repatch trigger and restores the original gate
# in every installed claude-code version (macOS / Linux).
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"
PYTHON="$(command -v python3 || true)"

uname_s="$(uname -s)"
case "$uname_s" in
  Darwin)
    PLIST_DST="$HOME_DIR/Library/LaunchAgents/com.persistent-cc-gauge.plist"
    if [[ -f "$PLIST_DST" ]]; then
      echo ">> Unloading + removing LaunchAgent"
      launchctl unload "$PLIST_DST" 2>/dev/null || true
      rm -f "$PLIST_DST"
    fi
    ;;
  Linux)
    if systemctl --user list-unit-files 2>/dev/null | grep -q persistent-cc-gauge.path; then
      echo ">> Disabling + removing systemd units"
      systemctl --user disable --now persistent-cc-gauge.path 2>/dev/null || true
      rm -f "$HOME_DIR/.config/systemd/user/persistent-cc-gauge.path" \
            "$HOME_DIR/.config/systemd/user/persistent-cc-gauge.service"
      systemctl --user daemon-reload
    fi
    ;;
esac

if [[ -n "$PYTHON" ]]; then
  echo ">> Restoring the original gate in all installed versions"
  "$PYTHON" "$REPO/scripts/patch_gauge.py" --restore
fi

echo
echo ">> Uninstalled. Reload the VSCode window to revert to the default behavior."
