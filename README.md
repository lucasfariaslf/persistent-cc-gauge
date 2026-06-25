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
`index.js`, so the patch has to run again. The trigger watches the extension
registry and re-runs the idempotent patcher when a new version lands:

```
extension update -> extensions.json changes -> trigger fires -> patch re-applied
```

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

prefetch-context eagerly launches the Claude core when the panel mounts. Drop
that transform if you do not want it.

## Manual use

```bash
python3 scripts/patch_gauge.py            # apply (idempotent)
python3 scripts/patch_gauge.py --dry-run  # preview
python3 scripts/patch_gauge.py --restore  # undo
./uninstall.sh                            # remove trigger + restore original
```

Covers VSCode, Insiders, the remote/SSH/WSL server, Cursor, and Windsurf. The
auto-trigger only watches VSCode stable; re-run manually for the others.

Modifies a bundled extension file only. Does not touch your code, settings, or
auth. Writes are atomic. Community tweak, not affiliated with Anthropic.
