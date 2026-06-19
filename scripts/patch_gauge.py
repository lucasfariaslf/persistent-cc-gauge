#!/usr/bin/env python3
"""
Always-show the Claude Code VSCode context-usage gauge.

THE PROBLEM
-----------
The Claude Code VSCode extension hides the little context-usage pie (next to the
chat input box) until you have used >=50% of the context window. The webview
bundle gates it with a single statement inside the usage component:

    if(c>=50)return null      # c = percent of context REMAINING

So while >=50% remains, the component renders nothing.

THE FIX
-------
Remove that one statement. The gauge then renders at every usage level. We keep
the adjacent `if(t===0)return null` guard so it still stays hidden before any
tokens are counted (otherwise a meaningless 0% pie shows at startup).

This script:
  * finds EVERY installed claude-code extension (all versions / all arch builds),
  * patches only the ones that still contain the gate,
  * leaves a marker comment so re-runs are no-ops (idempotent),
  * can undo the change with --restore (re-installs the gate).

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

# The exact statement that hides the gauge, and the marker we swap in for it.
GATE = "if(c>=50)return null"
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

    gates = data.count(GATE)
    if gates == 0:
        if MARKER in data:
            return "already"
        return "no-gate (bundle changed? see README)"
    if gates > 1:
        return f"error:gate-found-{gates}-times (refusing to guess)"

    if dry_run:
        return "would-patch"
    atomic_write(path, data.replace(GATE, MARKER, 1))
    return "patched"


def restore_one(path: str, dry_run: bool) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError as exc:
        return f"error:read {exc}"

    if MARKER not in data:
        return "not-patched"
    if dry_run:
        return "would-restore"
    atomic_write(path, data.replace(MARKER, GATE, 1))
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
