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
next, without review. The patcher only swaps exact, unique strings (and refuses
if a match is not unique), is standard-library Python, writes atomically, and is
fully reversible with `--restore`.

## What it changes

Three string transforms on `webview/index.js`, each marked `/*gauge-always*/`
for idempotency and `--restore`:

| transform        | effect                                                        | robust? |
|------------------|---------------------------------------------------------------|---------|
| visibility-guard | drops the 50% gate; hides only until real usage is reported   | yes     |
| continuous-pie   | continuous arc, exact at every %, colored green/yellow/red    | no      |
| prefetch-context | seeds usage on mount so the gauge shows on an idle session    | no      |

The last two match minified identifiers that the bundler renames on each
release. When they stop matching, the patcher skips them (the gauge still shows
correct numbers, just a coarse pie and no idle prefetch) and prints
`[skipped: ...]`. Re-match by updating the `orig`/`patched` strings in
`scripts/patch_gauge.py`; versions in `SUPPORTED_OPTIONAL_VERSIONS` fail loudly
if they regress instead of skipping silently.

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
An update can change the bundle so the optional transforms stop matching, and
modifying the extension may affect official support. `--restore` reverses the
transforms in place rather than restoring a saved copy; if you ever need a known-
good bundle, reinstall the extension.

It does not touch your code, settings, or auth, only the extension's
`webview/index.js`. Writes are atomic. Community tweak, not affiliated with
Anthropic; check your own obligations before using it.
