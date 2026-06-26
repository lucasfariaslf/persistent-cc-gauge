# Changelog

## 0.1.0

Initial release as a VS Code extension (previously a Python script plus an
OS-level watcher).

- On startup, patch the Claude Code webview bundle so the context-usage gauge is
  visible at every usage level, not only above 50%.
- Re-apply automatically after Claude Code updates (no separate watcher process).
- Structural matching survives the minified-identifier renames that happen on
  most extension updates; revert reconstructs the original from data embedded in
  each marker.
- Commands: Apply Patch Now, Revert Patch.
- Setting: `persistentCcGauge.enabled`.
