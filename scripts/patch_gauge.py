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

# The original guard block (two statements) and the replacement we swap in.
# ORIGINAL hides the gauge until >=50% used; PATCHED shows it at every level but
# still hides the "no data yet" state (used tokens or window not reported).
# The /*gauge-always*/ marker makes the patch detectable for idempotency/restore.
ORIGINAL = "if(t===0)return null;if(c>=50)return null"
PATCHED = "if(t<=0||e<=0)return null/*gauge-always*/"
MARKER = "/*gauge-always*/"

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

    hits = data.count(ORIGINAL)
    if hits == 0:
        if MARKER in data:
            return "already"
        return "no-guard-block (bundle changed? see README)"
    if hits > 1:
        return f"error:guard-block-found-{hits}-times (refusing to guess)"

    if dry_run:
        return "would-patch"
    atomic_write(path, data.replace(ORIGINAL, PATCHED, 1))
    return "patched"


def restore_one(path: str, dry_run: bool) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError as exc:
        return f"error:read {exc}"

    if PATCHED not in data:
        return "not-patched"
    if dry_run:
        return "would-restore"
    atomic_write(path, data.replace(PATCHED, ORIGINAL, 1))
    return "restored"


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
        if result in ("patched", "restored"):
            changed += 1

    log(f"done ({verb}); {changed} file(s) changed this run"
        + (" [dry-run]" if args.dry_run else ""))
    if changed:
        log("reload the VSCode window (Cmd/Ctrl+Shift+P -> 'Reload Window') "
            "to see the change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
