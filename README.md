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

Inside the usage component, two guard statements control visibility (`e` is
**used tokens**, `t` is the **effective context window**, `c` is the **percent of
context remaining**):

```js
if (t === 0) return null;   // weak "no window" guard
if (c >= 50) return null;   // the 50% gate — hides the gauge until 50% used
```

The `c >= 50` gate is the one we want gone. But it was also doing double duty: it
hid the **"no usage reported yet"** state. The extension resets used-tokens to 0
at the start of each send and only learns the context-window size once the model
responds, so before that the pie would read a fake-looking **0% used / 100%
remaining**. (The `t === 0` guard does *not* catch this, because the value passed
in is `contextWindow - maxOutputTokens - 13000`, i.e. `-13000` before any data.)

So the patch **replaces both guards with a single correct empty-state guard**:

```js
if (t <= 0 || e <= 0) return null;   // hide only when there's no real data yet
```

Result: the gauge shows at **every** usage level (no 50% gate), but stays hidden
until the model has actually reported token usage — no broken-looking 0%/100%
flash. A marker comment `/*gauge-always*/` is left in place so the patch is
detectable (idempotent re-runs, clean `--restore`).

> Note: because used-tokens resets on each send, the gauge briefly disappears in
> the moments right after you send a message and reappears once the model's first
> usage event returns. That's expected — the data genuinely isn't available in
> that window.

### Second change: an accurate pie below 50%

The numbers were always computed correctly, but the **pie drawing** wasn't built
for low values. The original renderer snaps the percentage into just three coarse
buckets (50 / 75 / 99) and looks up a pre-baked SVG arc — there is **no geometry
below 50%**, because the gauge was never shown there. So once it's always
visible, e.g. 8% used would draw a *half-filled* arc.

The patch replaces the pie renderer with a **continuous arc** (`stroke-dashoffset`
on a circle: 20×20 viewBox, center 10,10, r=5, circumference ≈31.42), exact at
every percentage. The faint background ring is unchanged (`currentColor` at 0.15
opacity); only the **filled arc** is recolored by **context used**, traffic-light
style:

| context used | arc color |
|---|---|
| < 30% | green `#3fb950` |
| 30–50% | yellow `#d29922` |
| > 50% | red `#f85149` |

Edit the `col=...` ternary in the `continuous-pie` `patched` string in
`scripts/patch_gauge.py` to change thresholds or colors.

> **Fragility note.** Unlike the visibility guard (which matches *semantic* code),
> the pie fix matches **minified identifiers** (`Iet`, `WEt`, `HEt`, `VEt`) that
> the bundler reassigns on every build — they are not stable across versions. So
> the pie transform is marked **optional**: if it doesn't match a given version,
> the script prints `[skipped: continuous-pie?]`, still applies the visibility
> guard, and moves on. In that state the gauge still shows the **correct numbers**;
> only the pie's fill is coarse below 50%. To re-enable it on a new version,
> update the `continuous-pie` `orig` string in `scripts/patch_gauge.py` to match
> that version's pie renderer.

### Third change: prepopulate usage on open

By default the gauge only gets numbers once the model first responds, because the
data it reads (`totalTokens` / `contextWindow`) is only produced **after a model
turn**. While a session is idle there is simply nothing to show, so the gauge
stays hidden until you send something.

To fix that, the patch injects a `useEffect` into the input footer that calls the
extension's own `getContextUsage()` on mount — the **same call `/context` uses**.
That forces the core to *compute* the baseline on demand (system prompt + tools +
memory + skills) and returns `{totalTokens, rawMaxTokens, percentage, ...}`. We
map those into the gauge's `usageData` signal, so the gauge shows usage as soon as
you open a session. We seed `maxOutputTokens` as `0`, so the opening figure can
read a hair lower than it will after the first turn — the first real response
overwrites it with the model's live values.

> **Cost / tradeoff.** `getContextUsage()` calls `launchClaude()` internally, so
> this **eagerly starts the Claude core process when the chat panel mounts**, even
> if you don't end up chatting. That's the deliberate price of populating an idle
> gauge — there is no cheaper way, because the numbers don't exist until the core
> computes them. (We tried `requestUsageUpdate()` first; it's a no-op while idle,
> so it never populated anything.) The call is wrapped in `try/catch` + an
> optional call (`?.()`) so it can never break the footer. Like the pie, it's
> **optional** — if the footer component's minified name drifts, it's skipped with
> a warning and the other fixes still apply.

### Why it needs to re-apply on every update

VSCode installs each extension version into its own folder
(`anthropic.claude-code-2.1.183-...`, `...-2.1.184-...`, etc.) and ships a fresh,
unpatched `index.js` each time. So the tweak has to be re-applied after every
update. This repo automates that with an OS-level trigger that watches VSCode
stable's `~/.vscode/extensions/extensions.json` and re-runs the (idempotent) patch
the moment a new version lands.

The patcher itself also covers Insiders, the remote/SSH/WSL server, Cursor, and
Windsurf — but the auto-trigger only watches **VSCode stable**. For those other
editors, re-run `scripts/patch_gauge.py` yourself after an update.

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
# Marker present (patched), original 50% gate gone, continuous pie present.
grep -c 'gauge-always'         ~/.vscode/extensions/anthropic.claude-code-*/webview/index.js
grep -c 'if(c>=50)return null'  ~/.vscode/extensions/anthropic.claude-code-*/webview/index.js
grep -c 'strokeDashoffset:off'  ~/.vscode/extensions/anthropic.claude-code-*/webview/index.js
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

- **It edits a bundled extension file.** Unsigned local modification of
  `webview/index.js`: it rewrites the gauge's visibility guard, the pie renderer,
  and adds a prefetch effect. It does not touch your code, settings, or auth.
  `--restore` reverts each applied transform to its original string.
- **The prefetch eagerly launches the Claude core** when the chat panel mounts
  (see "Third change"). Drop the `prefetch-context` transform if you don't want
  that.
- **If the bundle changes shape** in a future release, required transforms report
  `error:<name> not-found` / `error:<name> found-N-times` and the file is left
  untouched; optional transforms (pie, prefetch) print `[skipped: <name>?]` and
  the rest still apply. Update the matching `orig`/`patched` strings in the
  `TRANSFORMS` list in `scripts/patch_gauge.py`.
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
