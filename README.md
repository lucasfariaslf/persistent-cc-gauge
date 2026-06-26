# persistent-cc-gauge

The Claude Code VSCode extension only shows the context-usage pie once you pass
50% of the window. This patches the extension's bundled webview so the gauge is
always visible, and re-applies itself after every extension update.

## Install

Requires Python 3.

```bash
git clone https://github.com/lucasfariaslf/persistent-cc-gauge.git
cd persistent-cc-gauge
./install.sh        # Windows: powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

Then reload the VSCode window (`Cmd/Ctrl+Shift+P` then "Reload Window").

The installer patches every installed version and wires an auto-repatch trigger
(LaunchAgent on macOS, systemd `--user` path unit on Linux, Scheduled Task on
Windows).

## Why the auto-repatch

Each extension update installs into a new folder with a fresh, unpatched
`index.js`, so the patch has to run again. The trigger re-runs the idempotent
patcher when a new version lands:

```
extension update -> extensions.json changes -> trigger fires -> patch re-applied
```

On macOS and Linux the trigger watches `extensions.json` and fires on change.
Windows has no single-file watcher in Task Scheduler, so it runs at logon and
every 5 minutes instead; the patch is idempotent, so the repeated runs are
no-ops once applied.

The trigger keeps patching every future extension version until you run
`./uninstall.sh`. It re-applies the same patch to whatever the extension ships
next, without review. The patcher matches on code structure, requires a unique
match (and refuses otherwise), is standard-library Python, writes atomically,
and is fully reversible with `--restore`.

## What it changes

Three transforms on `webview/index.js`:

| transform        | effect                                                        |
|------------------|---------------------------------------------------------------|
| visibility-guard | drops the 50% gate; hides only until real usage is reported   |
| continuous-pie   | continuous arc, exact at every %, colored green/yellow/red    |
| prefetch-context | seeds usage on mount so the gauge shows on an idle session    |

Without continuous-pie the original renderer only has geometry for three coarse
buckets and draws a half-filled arc at low values; without prefetch-context an
idle session shows nothing until the first model reply.

The patcher reads and writes the bundle as bytes and matches the surrounding
code structure with regex, capturing the minified identifiers (function names,
JSX helpers, the useEffect alias) rather than hardcoding them. This survives the
identifier renames that happen on most extension updates, the same way
visibility-guard already does. Each transform embeds the exact bytes it replaced
(base64) in its marker, so `--restore` reconstructs the original byte-for-byte
without a separate backup. If a future update changes the structure itself, the
optional transforms skip with `[skipped: ...]` on unknown versions (the gauge
still shows correct numbers) and fail loudly on versions listed in
`SUPPORTED_OPTIONAL_VERSIONS`, so a regression is caught rather than silent.

prefetch-context is more than cosmetic: to populate an idle gauge it calls
`getContextUsage()` on mount, which eagerly launches the Claude core when the
chat panel opens, even if you never send a message. Drop that transform if you
do not want it.

## Manual use

```bash
python3 scripts/patch_gauge.py            # apply (idempotent)
python3 scripts/patch_gauge.py --dry-run  # preview
python3 scripts/patch_gauge.py --restore  # undo
./uninstall.sh                            # remove trigger + restore original
```

Covers VSCode, Insiders, the remote/SSH/WSL server, Cursor, and Windsurf. The
auto-trigger only watches VSCode stable; re-run manually for the others. Keep
the clone in place: the trigger and `--restore` both run from it.

## Caveats

Unsupported, use at your own risk. This edits a file Anthropic ships inside the
Claude Code extension, which is not a documented or supported integration point.
An update can change the bundle structure so the optional transforms stop
matching, and modifying the extension may affect official support. `--restore`
rebuilds the original bytes from data embedded in each marker rather than from a
saved copy; if a bundle is ever left in an unexpected state, reinstall the
extension.

It does not touch your code, settings, or auth, only the extension's
`webview/index.js`. Writes are atomic. Community tweak, not affiliated with
Anthropic; check your own obligations before using it.
