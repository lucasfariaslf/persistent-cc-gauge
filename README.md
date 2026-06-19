# Always-show the Claude Code context gauge (VSCode)

The Claude Code VSCode extension shows a small **context-usage pie** next to the
chat input box — but only **after you have used ≥50% of the context window**.
Below that, it renders nothing, so you can't see how much room you have left
early in a session.

This repo makes the gauge **always visible**, at every usage level, and keeps it
that way **automatically across extension updates**.

| | |
|---|---|
| **Before** | gauge hidden until ≥50% context used |
| **After** | gauge visible from the first tokens onward |

---

## How it works (what's actually changed)

The extension's UI is a bundled webview at:

```
<vscode-extensions-dir>/anthropic.claude-code-<version>/webview/index.js
```

Inside the usage component, one statement hides the gauge while plenty of
context remains (`c` is the **percent of context remaining**):

```js
let c = 100 - displayedPercent;
if (c >= 50) return null;   // <-- hides the gauge until you cross 50% used
```

The patch removes exactly that statement (replacing it with a harmless marker
comment `/*gauge-always*/`). The adjacent `if (t === 0) return null` guard is
**kept**, so the gauge still stays hidden before any tokens are counted (no
meaningless 0% pie at startup).

That's the entire change: **one statement removed, per installed version.**

### Why it needs to re-apply on every update

VSCode installs each extension version into its own folder
(`anthropic.claude-code-2.1.183-...`, `...-2.1.184-...`, etc.) and ships a fresh,
unpatched `index.js` each time. So the tweak has to be re-applied after every
update. This repo automates that with an OS-level trigger that watches VSCode's
extension registry file and re-runs the (idempotent) patch the moment a new
version lands.

---

## Install

Requires **Python 3** (used by the patch script). No other dependencies.

### macOS / Linux

```bash
git clone <this-repo> ~/repos/claude-code-context-gauge
cd ~/repos/claude-code-context-gauge
./install.sh
```

This:
1. patches every currently-installed claude-code version, and
2. installs an auto-repatch trigger:
   - **macOS** — a LaunchAgent watching `~/.vscode/extensions/extensions.json`
   - **Linux** — a systemd `--user` *path* unit watching the same file

Then **reload the VSCode window**: `Cmd/Ctrl+Shift+P → "Reload Window"`.

### Windows

```powershell
git clone <this-repo> $HOME\repos\claude-code-context-gauge
cd $HOME\repos\claude-code-context-gauge
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

This patches all installed versions and registers a Scheduled Task
(`ClaudeCodeContextGauge`) that re-applies the idempotent patch at logon and
every 5 minutes — so it self-heals after an update. Then reload the VSCode
window.

---

## Manual use (no auto-trigger)

You can also just run the patch yourself whenever you like:

```bash
python3 scripts/patch_gauge.py            # apply
python3 scripts/patch_gauge.py --dry-run  # preview, change nothing
python3 scripts/patch_gauge.py --restore  # undo (re-installs the gate)
```

It is **idempotent**: running it again on an already-patched install does
nothing. It patches **all** installed versions it finds, across VSCode, VSCode
Insiders, the remote/SSH/WSL server, Cursor, and Windsurf.

---

## Verify it worked

After patching + reloading the window, the context pie should appear next to the
chat input even at low usage. To confirm the file change:

```bash
# Should print the marker (patched) and NOT the gate.
grep -c 'gauge-always'        ~/.vscode/extensions/anthropic.claude-code-*/webview/index.js
grep -c 'if(c>=50)return null' ~/.vscode/extensions/anthropic.claude-code-*/webview/index.js
```

The patch script also writes a timestamped log to `scripts/patch_gauge.log`.

---

## Uninstall

```bash
# macOS / Linux
./uninstall.sh

# Windows
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1 -Uninstall
```

This removes the auto-trigger and restores the original gate in every installed
version.

---

## Notes, caveats, safety

- **It edits a bundled extension file.** That's an unsigned local modification.
  It does not touch your code, settings, or auth; it only flips one UI gate. The
  `--restore` path puts the file back byte-for-byte.
- **If the extension's bundle changes shape** in a future release (the gate
  string `if(c>=50)return null` disappears or appears multiple times), the script
  **refuses to guess** and reports `no-gate` or `error:gate-found-N-times`
  instead of corrupting the file. If that happens, the gate's surrounding code is
  documented above — update `GATE` in `scripts/patch_gauge.py` to match the new
  minified form, or open an issue.
- **Writes are atomic** (temp file + `os.replace`), so an interrupted run can't
  leave a half-written bundle.
- This is a community tweak, not affiliated with or supported by Anthropic.

---

## Repo layout

```
patch_gauge.py / scripts/        the cross-platform idempotent patcher (+ logs)
install.sh / uninstall.sh        macOS + Linux installer / remover
launchagent/                     macOS LaunchAgent template (auto-repatch)
systemd/                         Linux systemd --user path+service templates
scripts/install_windows.ps1      Windows installer/uninstaller (Scheduled Task)
```
