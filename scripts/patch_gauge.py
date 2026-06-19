#!/usr/bin/env python3
"""
Always-show the Claude Code VSCode context-usage gauge.

THE PROBLEM
-----------
The Claude Code VSCode extension hides the little context-usage pie (next to the
chat input box) until you have used >=50% of the context window. The webview
bundle gates it with two guard statements inside the usage component:

    if(t===0)return null      # t = effective context window (see below)
    if(c>=50)return null      # c = percent of context REMAINING

`c>=50` is the 50% gate we want gone. But it was ALSO doing double duty: it hid
the "no usage reported yet" state. At the start of a session and right after you
hit send, the extension resets used-tokens to 0 and hasn't yet received the
context-window size from the model, so the pie would read a fake-looking
"0% used / 100% remaining". The weak `t===0` guard does NOT catch this, because
the window value passed in is `contextWindow - maxOutputTokens - 13000`, which is
-13000 (not 0) before any data arrives.

THE FIX
-------
Replace BOTH guards with a single, correct empty-state guard:

    if(t<=0||e<=0)return null   # e = used tokens, t = effective window

This drops the 50% gate (so the gauge shows at every usage level) AND hides the
gauge until the model has actually reported token usage (no more 0%/100% flash).

This script:
  * finds EVERY installed claude-code extension (all versions / all arch builds),
  * patches only the ones that still contain the original guard block,
  * leaves a marker comment so re-runs are no-ops (idempotent),
  * can undo the change with --restore (re-installs the original guards).

It is cross-platform: it expands the VSCode extensions dir for macOS, Linux and
Windows. Run it once after installing/updating the extension, or wire it to the
auto-repatch trigger for your OS (see the repo README).

USAGE
-----
    python3 patch_gauge.py            # apply the tweak
    python3 patch_gauge.py --restore  # undo the tweak
    python3 patch_gauge.py --dry-run  # show what would change, touch nothing
"""

import argparse
import glob
import os
import sys
import time

# Each transform is an exact, unique string we swap (orig -> patched). The
# marker comments make every transform detectable for idempotency and --restore.
#
# 1) VISIBILITY guard. Original hides the gauge until >=50% used; the 50% gate
#    also (accidentally) hid the "no data yet" state. We replace BOTH guards with
#    one correct empty-state guard: show at every level, but stay hidden until the
#    model has actually reported token usage (no fake 0%/100% flash).
#
# 2) PIE renderer. The original pie (Iet) snaps the percentage into just three
#    coarse buckets (50/75/99) via WEt() and looks up a pre-rendered SVG arc. It
#    has NO geometry below 50%, because the gauge was never shown there. Once the
#    gauge is always visible, any low value (e.g. 8%) draws a half-filled arc.
#    We replace Iet with a continuous stroke-dashoffset arc that is exact at every
#    percentage (geometry: 20x20 viewBox, center 10,10, r=5, circumference ~31.42).
MARKER = "/*gauge-always*/"

TRANSFORMS = [
    {
        "name": "visibility-guard",
        "orig": "if(t===0)return null;if(c>=50)return null",
        "patched": "if(t<=0||e<=0)return null/*gauge-always*/",
    },
    {
        "name": "continuous-pie",
        # Optional: this transform matches MINIFIED identifiers (Iet/WEt/HEt/VEt)
        # that change between releases, so it may not match every version. When it
        # doesn't, we WARN and still apply the (robust) visibility guard rather
        # than failing the whole file. Without it the gauge still shows correct
        # numbers; only the pie's fill is coarse below 50%.
        "optional": True,
        "orig": (
            'function Iet({percentage:e,className:t}){let i=WEt(e),n=VEt[i];'
            'return oG.default.createElement("svg",{width:"20",height:"20",'
            'viewBox:"0 0 20 20",fill:"none",xmlns:"http://www.w3.org/2000/svg",'
            'className:t,style:{display:"block"}},n&&oG.default.createElement('
            '"path",{d:n,stroke:"currentColor",strokeOpacity:"0.15",'
            'strokeWidth:"1.5",strokeLinecap:"round"}),oG.default.createElement('
            '"path",{d:HEt[i],stroke:"var(--app-claude-clay-button-orange)",'
            'strokeWidth:"1.5",strokeLinecap:"round"}'
        ),
        "patched": (
            'function Iet({percentage:e,className:t}){/*gauge-always*/'
            'let p=Math.max(0,Math.min(100,e)),C=31.4159,off=C*(1-p/100),'
            # color by USED %: <30 green, 30-50 yellow, >50 red (traffic-light)
            'col=p<30?"#3fb950":p<=50?"#d29922":"#f85149";'
            'return oG.default.createElement("svg",{width:"20",height:"20",'
            'viewBox:"0 0 20 20",fill:"none",xmlns:"http://www.w3.org/2000/svg",'
            'className:t,style:{display:"block"}},oG.default.createElement('
            '"circle",{cx:"10",cy:"10",r:"5",stroke:"currentColor",'
            'strokeOpacity:"0.15",strokeWidth:"1.5"}),oG.default.createElement('
            '"circle",{cx:"10",cy:"10",r:"5",'
            'stroke:col,strokeWidth:"1.5",'
            'strokeLinecap:"round",strokeDasharray:C,strokeDashoffset:off,'
            'transform:"rotate(-90 10 10)"}'
        ),
    },
    {
        "name": "prefetch-on-mount",
        # Optional (matches a minified component name): when the input footer
        # mounts, ask the core for a fresh usage update so the gauge shows real
        # numbers as soon as you open/return to a session, instead of waiting for
        # the first model response. requestUsageUpdate() is a NO-OP if the core
        # isn't connected yet (no eager launch), so this is free on a cold window
        # and just degrades to the existing "appears after first response".
        "optional": True,
        "orig": "onTerminalCollaborator:h}){Xn();",
        "patched": (
            "onTerminalCollaborator:h}){Xn();"
            "/*gauge-always*/tp.useEffect(()=>{"
            "try{e.requestUsageUpdate?.()}catch{}},[]);"
        ),
    },
]

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_gauge.log")


def candidate_ext_dirs():
    """All plausible VSCode (and forks') extension directories for this OS."""
    home = os.path.expanduser("~")
    dirs = [
        os.path.join(home, ".vscode", "extensions"),            # VSCode (all OSes)
        os.path.join(home, ".vscode-insiders", "extensions"),   # VSCode Insiders
        os.path.join(home, ".vscode-server", "extensions"),     # Remote/SSH/WSL server
        os.path.join(home, ".cursor", "extensions"),            # Cursor
        os.path.join(home, ".windsurf", "extensions"),          # Windsurf
    ]
    # On Windows the dirs above already resolve under %USERPROFILE%; nothing extra
    # is needed because the extension layout is identical.
    return [d for d in dirs if os.path.isdir(d)]


def bundle_paths():
    """Every claude-code webview bundle across all extension dirs / versions."""
    paths = []
    for base in candidate_ext_dirs():
        pattern = os.path.join(
            base, "anthropic.claude-code-*", "webview", "index.js"
        )
        paths.extend(glob.glob(pattern))
    return sorted(set(paths))


def log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def label(path: str) -> str:
    """Human-readable id like 'anthropic.claude-code-2.1.183-darwin-arm64'."""
    parts = path.replace("\\", "/").split("/")
    for p in parts:
        if p.startswith("anthropic.claude-code-"):
            return p
    return path


def atomic_write(path: str, data: str) -> None:
    tmp = path + ".gauge.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)


def apply_one(path: str, dry_run: bool) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError as exc:
        return f"error:read {exc}"

    new = data
    applied, warns = [], []
    for t in TRANSFORMS:
        # Check "already patched" FIRST. Some transforms have an `orig` that is a
        # substring of their `patched` (we keep the anchor and append to it), so
        # counting `orig` after patching would still be >=1 and re-apply forever.
        if t["patched"] in new:
            continue                               # already done
        hits = new.count(t["orig"])
        if hits == 0:
            # Original form absent. For optional transforms this is just a
            # version mismatch -> warn and skip. For required ones it's fatal.
            if t.get("optional"):
                warns.append(t["name"] + "?")
                continue
            return f"error:{t['name']} not-found (bundle changed? see README)"
        if hits > 1:
            if t.get("optional"):
                warns.append(t["name"] + "x" + str(hits))
                continue
            return f"error:{t['name']} found-{hits}-times (refusing to guess)"
        new = new.replace(t["orig"], t["patched"], 1)
        applied.append(t["name"])

    suffix = ""
    if warns:
        suffix = " [skipped: " + ",".join(warns) + "]"
    if not applied:
        return "already" + suffix
    if dry_run:
        return "would-patch (" + ",".join(applied) + ")" + suffix
    atomic_write(path, new)
    return "patched (" + ",".join(applied) + ")" + suffix


def restore_one(path: str, dry_run: bool) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError as exc:
        return f"error:read {exc}"

    new = data
    reverted = []
    for t in TRANSFORMS:
        if t["patched"] in new:
            new = new.replace(t["patched"], t["orig"], 1)
            reverted.append(t["name"])

    if not reverted:
        return "not-patched"
    if dry_run:
        return "would-restore (" + ",".join(reverted) + ")"
    atomic_write(path, new)
    return "restored (" + ",".join(reverted) + ")"


def main() -> int:
    ap = argparse.ArgumentParser(description="Always-show Claude Code context gauge.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--restore", action="store_true", help="undo the tweak")
    ap.add_argument("--dry-run", action="store_true",
                    help="report actions without writing")
    args = ap.parse_args()

    paths = bundle_paths()
    if not paths:
        log("no claude-code webview bundles found "
            "(is the extension installed? check the dirs in candidate_ext_dirs)")
        return 0

    verb = "restore" if args.restore else "patch"
    changed = 0
    for path in paths:
        if args.restore:
            result = restore_one(path, args.dry_run)
        else:
            result = apply_one(path, args.dry_run)
        log(f"{label(path)}: {result}")
        if result.startswith("patched") or result.startswith("restored"):
            changed += 1

    log(f"done ({verb}); {changed} file(s) changed this run"
        + (" [dry-run]" if args.dry_run else ""))
    if changed:
        log("reload the VSCode window (Cmd/Ctrl+Shift+P -> 'Reload Window') "
            "to see the change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
