# persistent-cc-gauge

Keep the Claude Code context-usage gauge always visible in VSCode, and keep it
patched across extension updates.

The Claude Code VSCode extension shows a context-usage pie next to the chat
input, but only after you have used 50% or more of the context window. Below
that it renders nothing. This patches the extension's bundled webview so the
gauge is always visible, and re-applies after each extension update.

## What it changes

The extension UI is a bundled webview at:

```
<vscode-extensions-dir>/anthropic.claude-code-<version>/webview/index.js
```

The patcher applies three string transforms to that file. Each leaves a
`/*gauge-always*/` marker so runs are idempotent and `--restore` can revert.

1. visibility-guard. Replaces the two visibility guards
   (`if(t===0)return null;if(c>=50)return null`) with a single empty-state
   guard (`if(t<=0||e<=0)return null`). The gauge then shows at every usage
   level, but stays hidden until the model has reported real token usage, so
   there is no fake 0%/100% flash. This transform matches stable code and
   works across versions.

2. continuous-pie. Replaces the pie renderer with a continuous
   `stroke-dashoffset` arc that is exact at every percentage, and colors it by
   usage: green below 30%, yellow 30-50%, red above 50%. Without this the
   original renderer only has geometry for three coarse buckets (50/75/99) and
   draws a half-filled arc at low values once the gauge is always shown.

3. prefetch-context. Injects a `useEffect` into the input footer that calls the
   extension's `getContextUsage()` on mount, so the gauge is populated on a
   cold/idle session before the first model reply. This eagerly launches the
   Claude core when the panel mounts. Drop this transform if you do not want
   that.

Transforms 2 and 3 match minified identifiers that the bundler renames on every
release, so they are optional. On a version they do not match, the patcher
prints `[skipped: ...]`, applies the visibility guard, and continues. The gauge
still shows correct numbers; only the pie fill and idle prefetch are absent. To
re-enable them on a new version, update the matching `orig`/`patched` strings in
`scripts/patch_gauge.py` and add the version to `SUPPORTED_OPTIONAL_VERSIONS`.

Versions listed in `SUPPORTED_OPTIONAL_VERSIONS` fail loudly (non-zero exit) if
an optional transform stops matching, so a silent regression after an update is
caught instead of degrading unnoticed.

## Why it re-applies on every update

VSCode installs each extension version into its own folder and ships a fresh,
unpatched `index.js`. The patch has to run again after each update. The
installer wires an OS trigger that watches the extension registry and re-runs
the idempotent patcher when a new version lands.

## Install

Requires Python 3. No other dependencies.

macOS / Linux:

```bash
git clone https://github.com/lucasfariaslf/persistent-cc-gauge.git
cd persistent-cc-gauge
./install.sh
```

This patches every installed claude-code version and installs an auto-repatch
trigger (a LaunchAgent on macOS, a systemd `--user` path unit on Linux), both
watching `~/.vscode/extensions/extensions.json`. Then reload the VSCode window
(`Cmd/Ctrl+Shift+P` then "Reload Window").

Windows:

```powershell
git clone https://github.com/lucasfariaslf/persistent-cc-gauge.git
cd persistent-cc-gauge
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

This patches all installed versions and registers a Scheduled Task that
re-applies the patch at logon and every 5 minutes. Then reload the window.

The patcher covers VSCode, VSCode Insiders, the remote/SSH/WSL server, Cursor,
and Windsurf. The auto-trigger only watches VSCode stable; for the others,
re-run `scripts/patch_gauge.py` after an update.

## Manual use

```bash
python3 scripts/patch_gauge.py            # apply
python3 scripts/patch_gauge.py --dry-run  # preview, change nothing
python3 scripts/patch_gauge.py --restore  # undo
```

Idempotent. Patches all installed versions it finds.

## Verify

After patching and reloading, the gauge should appear at low usage. To check
the file:

```bash
f=~/.vscode/extensions/anthropic.claude-code-<version>/webview/index.js
grep -c 'gauge-always'        "$f"   # markers present
grep -c 'if(c>=50)return null' "$f"   # original gate gone (0)
grep -c 'strokeDashoffset:off' "$f"   # continuous pie present (1)
```

The patcher writes a timestamped log to `scripts/patch_gauge.log`.

## Uninstall

```bash
./uninstall.sh                                                    # macOS / Linux
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1 -Uninstall  # Windows
```

Removes the auto-trigger and restores the original gate in every installed
version.

## Notes

- This modifies a bundled extension file. It does not touch your code,
  settings, or auth. `--restore` reverts each applied transform.
- The prefetch transform eagerly launches the Claude core when the chat panel
  mounts. Remove the `prefetch-context` transform to avoid that.
- If a required transform stops matching, the file is left untouched and the
  patcher reports an error. Update the `orig`/`patched` strings in the
  `TRANSFORMS` list in `scripts/patch_gauge.py`.
- Writes are atomic (temp file plus `os.replace`).
- Community tweak. Not affiliated with or supported by Anthropic.

## Layout

```
scripts/patch_gauge.py       cross-platform idempotent patcher
install.sh / uninstall.sh    macOS and Linux installer / remover
launchagent/                 macOS LaunchAgent template
systemd/                     Linux systemd path + service templates
scripts/install_windows.ps1  Windows installer / uninstaller
```
