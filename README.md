# persistent-cc-gauge

A VS Code extension that keeps the Claude Code context-usage gauge always
visible, and re-applies itself after Claude Code updates.

The Claude Code extension only shows the context pie next to the chat input once
you pass 50% of the window. This patches its bundled webview so the gauge shows
at every usage level, draws a continuous colored arc, and is populated on an
idle session instead of only after the first reply.

It patches another extension's installed files, so it is not on the Marketplace.
Install from source.

## Install

```bash
git clone https://github.com/lucasfariaslf/persistent-cc-gauge.git
cd persistent-cc-gauge
npm run install:local
```

Then reload the VS Code window (`Cmd/Ctrl+Shift+P` then "Reload Window").
`install:local` copies the extension into `~/.vscode/extensions`. To build a
`.vsix` instead, run `npm run package` and install it with
`code --install-extension persistent-cc-gauge-*.vsix`.

Cursor and Windsurf load VS Code extensions the same way; install there too if
you use them. For a remote/SSH/WSL window, install into that host.

## How it works

On startup (`onStartupFinished`) the extension patches the Claude Code webview
bundle, then prompts you to reload. Each Claude Code update ships a fresh,
unpatched bundle, so re-applying on every startup is what makes the patch
persist. There is no separate watcher process. Toggle the startup behavior with
the `persistentCcGauge.enabled` setting, or run it on demand:

- Persistent CC Gauge: Apply Patch Now
- Persistent CC Gauge: Revert Patch

## What it changes

Three transforms on the bundle's `webview/index.js`:

| transform        | effect                                                        |
|------------------|---------------------------------------------------------------|
| visibility-guard | drops the 50% gate; hides only until real usage is reported   |
| continuous-pie   | continuous arc, exact at every %, colored green/yellow/red    |
| prefetch-context | seeds usage on mount so the gauge shows on an idle session    |

The transforms match the surrounding code structure and capture the minified
identifiers (function names, JSX helpers, the useEffect alias) rather than
hardcoding them, so they survive the identifier renames that happen on most
updates. Each embeds the exact bytes it replaced (base64) in its marker, so
Revert reconstructs the original. A pristine copy of the bundle is also saved
once alongside it (`.pcg.bak`) as a safety net.

If a future update changes the structure itself, the optional transforms
(continuous-pie, prefetch-context) are skipped and the gauge still shows correct
numbers via the visibility guard; re-match them in `src/patch.js`.

prefetch-context is more than cosmetic: to populate an idle gauge it calls
`getContextUsage()` on mount, which eagerly launches the Claude core when the
chat panel opens, even if you never send a message. Remove that transform from
`src/patch.js` if you do not want it.

## Upgrading from the script version

Earlier versions of this tool were a Python script plus an OS watcher
(LaunchAgent on macOS, a systemd user unit on Linux, a Scheduled Task on
Windows). Deleting the repo does not remove an already-installed watcher. If you
used it, remove the watcher: on macOS `launchctl unload` and delete
`~/Library/LaunchAgents/com.persistent-cc-gauge.plist`; on Linux
`systemctl --user disable --now persistent-cc-gauge.path`; on Windows delete the
`ClaudeCodeContextGauge` scheduled task. Then install this extension.

## Caveats

Unsupported, use at your own risk. This edits a file Anthropic ships inside the
Claude Code extension, which is not a documented or supported integration point.
An update can change the bundle structure so the optional transforms stop
matching, and modifying the extension may affect official support. It only
touches the Claude Code `webview/index.js`; it does not change your code,
settings, or auth. Not affiliated with Anthropic; check your own obligations
before using it.

## Develop

```bash
npm install
npm test     # node --test, unit tests for src/patch.js
npm run lint
```

`src/patch.js` holds the pure transform logic (`planPatch` / `planRevert`);
`extension.js` is the VS Code glue (resolve the bundle, atomic write, backup,
reload prompt).
