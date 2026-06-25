#!/usr/bin/env python3
"""
Always-show the Claude Code VSCode context-usage gauge.

Patches the extension's bundled webview/index.js so the context pie is visible
at every usage level, not only above 50%. Applies three string transforms, each
marked with /*gauge-always*/ so runs are idempotent and --restore can revert.

Finds every installed claude-code extension across VSCode, Insiders, the
remote/SSH/WSL server, Cursor, and Windsurf. Run after installing or updating
the extension, or wire it to the auto-repatch trigger (see README).

Usage:
    python3 patch_gauge.py            # apply
    python3 patch_gauge.py --restore  # undo
    python3 patch_gauge.py --dry-run  # preview, change nothing
"""

import argparse
import glob
import re
import os
import sys
import time

# Each transform swaps an exact, unique string (orig -> patched). The marker
# makes every transform detectable for idempotency and --restore.
#
# 1) visibility-guard: replaces both guards (if(t===0)return null;if(c>=50)
#    return null) with one empty-state guard (if(t<=0||e<=0)return null). e is
#    used tokens, t is the effective window. Shows the gauge at every level but
#    stays hidden until the model reports real usage, avoiding a 0%/100% flash.
#    Matches stable code, so it works across versions.
#
# 2) continuous-pie: replaces the bucketed pie renderer with a continuous
#    stroke-dashoffset arc (20x20 viewBox, center 10,10, r=5, circumference
#    ~31.42), colored by usage. The original only has geometry for 50/75/99.
#
# 3) prefetch-context: injects a useEffect calling getContextUsage() on mount so
#    the gauge is populated on an idle session. This launches the Claude core
#    when the panel mounts.
#
# Transforms 2 and 3 match minified identifiers that change between releases, so
# they are optional. See SUPPORTED_OPTIONAL_VERSIONS for the fail-loud behavior.
MARKER = "/*gauge-always*/"

TRANSFORMS = [
    {
        "name": "visibility-guard",
        "orig": "if(t===0)return null;if(c>=50)return null",
        "patched": "if(t<=0||e<=0)return null/*gauge-always*/",
    },
    {
        "name": "continuous-pie",
        # Optional: matches minified identifiers that change between releases. On
        # a non-matching version the gauge still shows correct numbers; only the
        # pie fill is coarse below 50%.
        "optional": True,
        # Matched against 2.1.187 (renderer bXe, JSX helpers E/b). Earlier
        # versions used Iet + oG.default.createElement.
        "orig": (
            'function bXe({percentage:e,className:t}){let i=z9t(e),n=W9t[i];'
            'return E("svg",{width:"20",height:"20",viewBox:"0 0 20 20",'
            'fill:"none",xmlns:"http://www.w3.org/2000/svg",className:t,'
            'style:{display:"block"},children:[n&&b("path",{d:n,'
            'stroke:"currentColor",strokeOpacity:"0.15",strokeWidth:"1.5",'
            'strokeLinecap:"round"}),b("path",{d:V9t[i],'
            'stroke:"var(--app-claude-clay-button-orange)",strokeWidth:"1.5",'
            'strokeLinecap:"round"})]})}'
        ),
        "patched": (
            'function bXe({percentage:e,className:t}){/*gauge-always*/'
            'let p=Math.max(0,Math.min(100,e)),C=31.4159,off=C*(1-p/100),'
            # used %: <30 green, 30-50 yellow, >50 red
            'col=p<30?"#3fb950":p<=50?"#d29922":"#f85149";'
            'return E("svg",{width:"20",height:"20",viewBox:"0 0 20 20",'
            'fill:"none",xmlns:"http://www.w3.org/2000/svg",className:t,'
            'style:{display:"block"},children:[b("circle",{cx:"10",cy:"10",'
            'r:"5",stroke:"currentColor",strokeOpacity:"0.15",'
            'strokeWidth:"1.5"}),b("circle",{cx:"10",cy:"10",r:"5",'
            'stroke:col,strokeWidth:"1.5",strokeLinecap:"round",'
            'strokeDasharray:C,strokeDashoffset:off,'
            'transform:"rotate(-90 10 10)"})]})}'
        ),
    },
    {
        "name": "prefetch-context",
        # Optional: on mount, call getContextUsage() and seed the gauge's
        # usageData signal so it shows on an idle session before the first model
        # reply. getContextUsage() computes the baseline on demand (it launches
        # the core); requestUsageUpdate() is a no-op while idle. The first real
        # turn overwrites the seeded values. Wrapped in try/catch and an optional
        # call so it cannot break the footer; runs once on mount.
        "optional": True,
        # Matched against 2.1.187 (footer body starts onTerminalCollaborator:h})
        # {zn();, useEffect minified to pe, session store e). Earlier versions
        # started {Xn(); + tp.useEffect.
        "orig": "onTerminalCollaborator:h}){zn();",
        "patched": (
            "onTerminalCollaborator:h}){zn();"
            "/*gauge-always*/pe(()=>{try{"
            "e.getContextUsage?.().then(a=>{"
            "let u=a&&a.usage;if(!u)return;"
            "e.usageData.value={...e.usageData.value,"
            "totalTokens:u.totalTokens,contextWindow:u.rawMaxTokens,"
            "maxOutputTokens:0};"
            "}).catch(()=>{});"
            "}catch{}},[]);"
        ),
    },
]

# Versions where the optional transforms are known to match. An unknown version
# that skips them is expected (soft warning). A version listed here that skips is
# a regression, so it fails with a non-zero exit instead of degrading silently.
# Add a version here after re-matching the optional transforms for it.
SUPPORTED_OPTIONAL_VERSIONS = {
    "2.1.187",
}

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


def version_of(path: str) -> str:
    """Extract the bare semver from a path, e.g. '2.1.187' (or '' if absent).

    Folder names look like 'anthropic.claude-code-2.1.187-darwin-arm64', so we
    strip the prefix and keep the leading dotted-number run.
    """
    name = label(path)
    rest = name.replace("anthropic.claude-code-", "", 1)
    m = re.match(r"\d+(?:\.\d+)*", rest)
    return m.group(0) if m else ""


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

    # On a version we've declared supported, an OPTIONAL transform that fails to
    # match is a silent regression, not an expected version skip -> treat it as a
    # hard error so the run fails loudly instead of degrading unnoticed.
    fail_closed = version_of(path) in SUPPORTED_OPTIONAL_VERSIONS

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
            # Original form absent. For optional transforms this is normally just
            # a version mismatch -> warn and skip. But on a SUPPORTED version it
            # is a silent regression -> fail loudly. Required transforms: fatal.
            if t.get("optional") and not fail_closed:
                warns.append(t["name"] + "?")
                continue
            return (f"error:{t['name']} not-found on supported version "
                    f"{version_of(path)} (bundle re-minified? re-match it)"
                    if t.get("optional")
                    else f"error:{t['name']} not-found (bundle changed? see README)")
        if hits > 1:
            if t.get("optional") and not fail_closed:
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
    errors = 0
    for path in paths:
        if args.restore:
            result = restore_one(path, args.dry_run)
        else:
            result = apply_one(path, args.dry_run)
        log(f"{label(path)}: {result}")
        if result.startswith("patched") or result.startswith("restored"):
            changed += 1
        elif result.startswith("error:"):
            errors += 1

    log(f"done ({verb}); {changed} file(s) changed this run"
        + (f"; {errors} error(s)" if errors else "")
        + (" [dry-run]" if args.dry_run else ""))
    if changed:
        log("reload the VSCode window (Cmd/Ctrl+Shift+P -> 'Reload Window') "
            "to see the change")
    if errors:
        # Fail loudly: a supported version that didn't fully patch (or a required
        # transform that vanished) must not pass silently.
        log("FAILED: one or more bundles did not patch as expected (see above)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
