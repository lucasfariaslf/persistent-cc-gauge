#!/usr/bin/env bash
#
# Installer for the "always-show Claude Code context gauge" tweak (macOS / Linux).
#
#   * applies the patch to every currently-installed claude-code version
#   * installs an auto-repatch trigger so it re-applies after each update:
#       - macOS: a LaunchAgent watching ~/.vscode/extensions/extensions.json
#       - Linux: a systemd --user path unit watching the same file
#
# Re-running is safe. Use ./uninstall.sh to remove everything.
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"
PYTHON="$(command -v python3 || true)"

if [[ -z "$PYTHON" ]]; then
  echo "error: python3 not found on PATH. Install Python 3 and retry." >&2
  exit 1
fi

# The background trigger must use a STABLE interpreter, not whatever venv happens
# to be active in this shell (the patch script is stdlib-only, so any Python 3
# works). Prefer a system python that won't disappear; fall back to PATH python.
TRIGGER_PYTHON="$PYTHON"
for cand in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [[ -x "$cand" ]]; then TRIGGER_PYTHON="$cand"; break; fi
done
if [[ -n "${VIRTUAL_ENV:-}" && "$PYTHON" == "$VIRTUAL_ENV"* && "$TRIGGER_PYTHON" == "$VIRTUAL_ENV"* ]]; then
  echo "warning: only a venv python was found; the auto-repatch trigger will" >&2
  echo "         depend on $TRIGGER_PYTHON staying present." >&2
fi

echo ">> Applying the patch to currently-installed versions..."
"$PYTHON" "$REPO/scripts/patch_gauge.py"

uname_s="$(uname -s)"
case "$uname_s" in
  Darwin)
    PLIST_SRC="$REPO/launchagent/com.claude-code-context-gauge.plist.template"
    PLIST_DST="$HOME_DIR/Library/LaunchAgents/com.claude-code-context-gauge.plist"
    LABEL="com.claude-code-context-gauge"

    echo ">> Installing LaunchAgent -> $PLIST_DST"
    mkdir -p "$HOME_DIR/Library/LaunchAgents"
    sed -e "s|__HOME__|$HOME_DIR|g" -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$TRIGGER_PYTHON|g" \
      "$PLIST_SRC" > "$PLIST_DST"

    # Reload cleanly (ignore "not loaded" on first install).
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo ">> LaunchAgent loaded. It will re-patch automatically on every update."
    ;;

  Linux)
    UNIT_DIR="$HOME_DIR/.config/systemd/user"
    echo ">> Installing systemd --user path+service units -> $UNIT_DIR"
    mkdir -p "$UNIT_DIR"
    sed -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$TRIGGER_PYTHON|g" -e "s|__HOME__|$HOME_DIR|g" \
      "$REPO/systemd/claude-code-context-gauge.service.template" \
      > "$UNIT_DIR/claude-code-context-gauge.service"
    sed -e "s|__HOME__|$HOME_DIR|g" \
      "$REPO/systemd/claude-code-context-gauge.path.template" \
      > "$UNIT_DIR/claude-code-context-gauge.path"

    systemctl --user daemon-reload
    systemctl --user enable --now claude-code-context-gauge.path
    echo ">> systemd path unit enabled. It will re-patch automatically on every update."
    echo "   (If this is a headless box, you may need: loginctl enable-linger $USER)"
    ;;

  *)
    echo ">> OS '$uname_s' has no auto-trigger installer here."
    echo "   The patch was applied. Re-run scripts/patch_gauge.py manually after updates,"
    echo "   or see the README for Windows (Task Scheduler) instructions."
    ;;
esac

echo
echo ">> Done. Reload the VSCode window (Cmd/Ctrl+Shift+P -> 'Reload Window') to see the gauge."
