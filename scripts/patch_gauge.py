#!/usr/bin/env python3
"""
Always-show the Claude Code VSCode context-usage gauge.

Patches the extension's bundled webview/index.js so the context pie is visible
at every usage level, not only above 50%. Three transforms; runs are idempotent
and --restore reverts them.

The file is treated as bytes so --restore is byte-identical. The two optional
transforms match the code STRUCTURE with regex and capture the minified
identifiers, instead of hardcoding names, so they survive the identifier renames
that happen on most extension updates. Each optional transform embeds the exact
bytes it replaced (base64) in its marker, so --restore reconstructs the original
without a sidecar backup.

Finds every installed claude-code extension across VSCode, Insiders, the
remote/SSH/WSL server, Cursor, and Windsurf. Run after installing or updating
the extension, or wire it to the auto-repatch trigger (see README).

Usage:
    python3 patch_gauge.py            # apply
    python3 patch_gauge.py --restore  # undo
    python3 patch_gauge.py --dry-run  # preview; writes nothing, not even the log
"""

import argparse
import base64
import glob
import os
import re
import sys
import time

ID = rb"[A-Za-z_$][\w$]*"   # a minified JS identifier

# 1) visibility-guard: replaces both guards (if(t===0)return null;if(c>=50)
#    return null) with one empty-state guard (if(t<=0||e<=0)return null). Shows
#    the gauge at every level but stays hidden until the model reports real
#    usage, avoiding a 0%/100% flash. Matches stable code, so it is exact.
VIS_ORIG = b"if(t===0)return null;if(c>=50)return null"
VIS_PATCHED = b"if(t<=0||e<=0)return null/*gauge-always*/"

# 2) continuous-pie: replaces the bucketed pie renderer with a continuous
#    stroke-dashoffset arc, colored by usage. The find regex captures the
#    renderer name (fn) and the JSX helpers (E for the svg element, B for its
#    children); the bucket-table identifiers are matched but not reused, because
#    the replacement computes the arc directly.
PIE_FIND = re.compile(
    rb"function (?P<fn>" + ID + rb")\(\{percentage:e,className:t\}\)\{"
    rb"let i=" + ID + rb"\(e\),n=" + ID + rb"\[i\];"
    rb'return (?P<E>' + ID + rb')\("svg",\{width:"20",height:"20",'
    rb'viewBox:"0 0 20 20",fill:"none",xmlns:"http://www\.w3\.org/2000/svg",'
    rb'className:t,style:\{display:"block"\},children:\[n&&(?P<B>' + ID + rb')\("path",\{d:n,'
    rb'stroke:"currentColor",strokeOpacity:"0\.15",strokeWidth:"1\.5",'
    rb'strokeLinecap:"round"\}\),(?P=B)\("path",\{d:' + ID + rb'\[i\],'
    rb'stroke:"var\(--app-claude-clay-button-orange\)",strokeWidth:"1\.5",'
    rb'strokeLinecap:"round"\}\)\]\}\)\}'
)
PIE_MARK = b"/*gauge-always:continuous-pie:v1:"
# Exact patched block (no .*?), identifier slots open, b64 captured for restore.
PIE_RESTORE = re.compile(
    rb"function " + ID + rb"\(\{percentage:e,className:t\}\)\{"
    rb"/\*gauge-always:continuous-pie:v1:(?P<b64>[A-Za-z0-9_=-]+)\*/"
    rb"let p=Math\.max\(0,Math\.min\(100,e\)\),C=31\.4159,off=C\*\(1-p/100\),"
    rb'col=p<30\?"#3fb950":p<=50\?"#d29922":"#f85149";'
    rb'return ' + ID + rb'\("svg",\{width:"20",height:"20",viewBox:"0 0 20 20",'
    rb'fill:"none",xmlns:"http://www\.w3\.org/2000/svg",className:t,'
    rb'style:\{display:"block"\},children:\[' + ID + rb'\("circle",\{cx:"10",cy:"10",'
    rb'r:"5",stroke:"currentColor",strokeOpacity:"0\.15",strokeWidth:"1\.5"\}\),'
    + ID + rb'\("circle",\{cx:"10",cy:"10",r:"5",stroke:col,strokeWidth:"1\.5",'
    rb'strokeLinecap:"round",strokeDasharray:C,strokeDashoffset:off,'
    rb'transform:"rotate\(-90 10 10\)"\}\)\]\}\)\}'
)


def build_pie(m, _data):
    fn, e_helper, b_helper = m.group("fn"), m.group("E"), m.group("B")
    b64 = base64.urlsafe_b64encode(m.group(0))
    return (
        b"function " + fn + b"({percentage:e,className:t}){"
        b"/*gauge-always:continuous-pie:v1:" + b64 + b"*/"
        b"let p=Math.max(0,Math.min(100,e)),C=31.4159,off=C*(1-p/100),"
        b'col=p<30?"#3fb950":p<=50?"#d29922":"#f85149";'
        b'return ' + e_helper + b'("svg",{width:"20",height:"20",viewBox:"0 0 20 20",'
        b'fill:"none",xmlns:"http://www.w3.org/2000/svg",className:t,'
        b'style:{display:"block"},children:[' + b_helper + b'("circle",{cx:"10",cy:"10",'
        b'r:"5",stroke:"currentColor",strokeOpacity:"0.15",strokeWidth:"1.5"}),'
        + b_helper + b'("circle",{cx:"10",cy:"10",r:"5",stroke:col,strokeWidth:"1.5",'
        b'strokeLinecap:"round",strokeDasharray:C,strokeDashoffset:off,'
        b'transform:"rotate(-90 10 10)"})]})}'
    )


# 3) prefetch-context: injects a useEffect calling getContextUsage() on mount so
#    the gauge is populated on an idle session before the first model reply. The
#    find regex captures the footer init-call name; the useEffect alias (pe) is
#    captured separately from the bundle and must be unique.
FOOTER_FIND = re.compile(rb"onTerminalCollaborator:h\}\)\{(?P<call>" + ID + rb")\(\);")
FOOTER_MARK = b"/*gauge-always:prefetch-context:v1:"
PE_FIND = re.compile(rb"(?P<pe>" + ID + rb")=function\(e,t\)\{return " + ID + rb"(?:\." + ID + rb")*\.current\.useEffect\(e,t\)\}")
FOOTER_RESTORE = re.compile(
    rb"onTerminalCollaborator:h\}\)\{" + ID + rb"\(\);"
    rb"/\*gauge-always:prefetch-context:v1:(?P<b64>[A-Za-z0-9_=-]+)\*/"
    + ID + rb"\(\(\)=>\{try\{e\.getContextUsage\?\.\(\)\.then\(a=>\{"
    rb"let u=a&&a\.usage;if\(!u\)return;"
    rb"e\.usageData\.value=\{\.\.\.e\.usageData\.value,"
    rb"totalTokens:u\.totalTokens,contextWindow:u\.rawMaxTokens,maxOutputTokens:0\};"
    rb"\}\)\.catch\(\(\)=>\{\}\);\}catch\{\}\},\[\]\);"
)


def build_footer(m, data):
    pes = PE_FIND.findall(data)
    if len(pes) != 1:
        raise ValueError(f"useEffect-alias-count-{len(pes)}")
    pe = pes[0]
    call = m.group("call")
    b64 = base64.urlsafe_b64encode(m.group(0))
    return (
        b"onTerminalCollaborator:h}){" + call + b"();"
        b"/*gauge-always:prefetch-context:v1:" + b64 + b"*/"
        + pe + b"(()=>{try{e.getContextUsage?.().then(a=>{"
        b"let u=a&&a.usage;if(!u)return;"
        b"e.usageData.value={...e.usageData.value,"
        b"totalTokens:u.totalTokens,contextWindow:u.rawMaxTokens,maxOutputTokens:0};"
        b"}).catch(()=>{});}catch{}},[]);"
    )


TRANSFORMS = [
    {"name": "visibility-guard", "kind": "str", "optional": False,
     "orig": VIS_ORIG, "patched": VIS_PATCHED},
    {"name": "continuous-pie", "kind": "regex", "optional": True,
     "find": PIE_FIND, "build": build_pie, "marker": PIE_MARK,
     "restore": PIE_RESTORE},
    {"name": "prefetch-context", "kind": "regex", "optional": True,
     "find": FOOTER_FIND, "build": build_footer, "marker": FOOTER_MARK,
     "restore": FOOTER_RESTORE},
]

# Versions where the optional transforms are expected to apply. With structural
# matching they normally match every release, so this rarely needs updating. A
# listed version that fails to apply an optional transform exits non-zero (a
# structural change Anthropic made), instead of silently degrading.
SUPPORTED_OPTIONAL_VERSIONS = {
    "2.1.190",
    "2.1.191",
    "2.1.193",
}

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_gauge.log")

# Set by --dry-run so log() prints to stdout but does not touch the log file:
# a dry run must write nothing at all.
_LOG_TO_FILE = True


def log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    if not _LOG_TO_FILE:
        return
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


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
    return [d for d in dirs if os.path.isdir(d)]


def bundle_paths():
    """Every claude-code webview bundle across all extension dirs / versions."""
    paths = []
    for base in candidate_ext_dirs():
        pattern = os.path.join(base, "anthropic.claude-code-*", "webview", "index.js")
        paths.extend(glob.glob(pattern))
    return sorted(set(paths))


def label(path: str) -> str:
    """Human-readable id like 'anthropic.claude-code-2.1.183-darwin-arm64'."""
    for p in path.replace("\\", "/").split("/"):
        if p.startswith("anthropic.claude-code-"):
            return p
    return path


def version_of(path: str) -> str:
    """Extract the bare semver from a path, e.g. '2.1.187' (or '' if absent)."""
    rest = label(path).replace("anthropic.claude-code-", "", 1)
    m = re.match(r"\d+(?:\.\d+)*", rest)
    return m.group(0) if m else ""


def atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".gauge.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _apply_str(t, data):
    """Returns (new_data, status). status: applied|already|('error',msg)."""
    if t["patched"] in data:
        return data, "already"
    hits = data.count(t["orig"])
    if hits == 0:
        return data, ("error", f"{t['name']} not-found (bundle changed? see README)")
    if hits > 1:
        return data, ("error", f"{t['name']} found-{hits}-times (refusing to guess)")
    return data.replace(t["orig"], t["patched"], 1), "applied"


def _apply_regex(t, data):
    """Returns (new_data, status). status: applied|already|skip0|('skipN',n)|('error',msg)."""
    marker = t["marker"]
    mcount = data.count(marker)
    if mcount >= 1:
        # Already patched: the patched block must still be intact for restore.
        if len(t["restore"].findall(data)) != mcount:
            return data, ("error", f"{t['name']} marker-present-but-block-corrupt")
        return data, "already"
    matches = list(t["find"].finditer(data))
    if not matches:
        return data, "skip0"
    if len(matches) > 1:
        return data, ("skipN", len(matches))
    m = matches[0]
    try:
        patched = t["build"](m, data)
    except ValueError as exc:
        # A precondition the build needs (e.g. a unique useEffect alias) was not
        # met. Treat like a structural miss: soft skip on unknown versions,
        # fail-closed on supported ones. Never block the required guard.
        return data, ("precond", str(exc))
    cand = data[:m.start()] + patched + data[m.end():]
    # Postconditions. Note: we do NOT assert the find regex is gone -- the
    # prefetch transform prepends and keeps its anchor, so find still matches the
    # patched block; the marker check guards against re-patching. We already
    # required exactly one find match above, so no second site can remain.
    if cand.count(marker) != 1:
        return data, ("error", f"{t['name']} postcond-marker")
    if len(t["restore"].findall(cand)) != 1:
        return data, ("error", f"{t['name']} postcond-restore")
    return cand, "applied"


def apply_one(path: str, dry_run: bool) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return f"error:read {exc}"

    # On a declared-supported version, an optional transform that fails to match
    # is a structural regression, not an expected skip -> fail loudly.
    fail_closed = version_of(path) in SUPPORTED_OPTIONAL_VERSIONS

    new = data
    applied, warns = [], []
    for t in TRANSFORMS:
        if t["kind"] == "str":
            new, status = _apply_str(t, new)
        else:
            new, status = _apply_regex(t, new)

        if status == "applied":
            applied.append(t["name"])
        elif status == "already":
            continue
        elif status == "skip0":
            if t["optional"] and not fail_closed:
                warns.append(t["name"] + "?")
            else:
                return (f"error:{t['name']} not-found on supported version "
                        f"{version_of(path)} (structure changed? re-match it)")
        elif isinstance(status, tuple) and status[0] == "skipN":
            if t["optional"] and not fail_closed:
                warns.append(t["name"] + "x" + str(status[1]))
            else:
                return f"error:{t['name']} found-{status[1]}-times (refusing to guess)"
        elif isinstance(status, tuple) and status[0] == "precond":
            if t["optional"] and not fail_closed:
                warns.append(t["name"] + "?")
            else:
                return (f"error:{t['name']} {status[1]} on supported version "
                        f"{version_of(path)}")
        elif isinstance(status, tuple) and status[0] == "error":
            return "error:" + status[1]

    suffix = " [skipped: " + ",".join(warns) + "]" if warns else ""
    if not applied:
        return "already" + suffix
    if dry_run:
        return "would-patch (" + ",".join(applied) + ")" + suffix
    atomic_write(path, new)
    return "patched (" + ",".join(applied) + ")" + suffix


def _restore_regex(t, data):
    """Returns (new_data, reverted_bool, error_or_None)."""
    mcount = data.count(t["marker"])
    if mcount == 0:
        return data, False, None
    matches = list(t["restore"].finditer(data))
    # Every marker must have an intact patched block behind it; otherwise the
    # file was tampered with and we refuse rather than partially restore.
    if len(matches) != mcount:
        return data, False, f"{t['name']} restore-block-corrupt"
    out = data
    for m in reversed(matches):   # reverse so earlier offsets stay valid
        try:
            orig = base64.urlsafe_b64decode(m.group("b64"))
        except (ValueError, base64.binascii.Error):
            return data, False, f"{t['name']} bad-b64"
        if not t["find"].fullmatch(orig):
            return data, False, f"{t['name']} restore-sanity"
        out = out[:m.start()] + orig + out[m.end():]
    return out, True, None


def restore_one(path: str, dry_run: bool) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return f"error:read {exc}"

    new = data
    reverted = []
    for t in TRANSFORMS:
        if t["kind"] == "str":
            if t["patched"] in new:
                new = new.replace(t["patched"], t["orig"], 1)
                reverted.append(t["name"])
        else:
            new, did, err = _restore_regex(t, new)
            if err:
                return "error:" + err
            if did:
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
                    help="report actions without writing anything (no log)")
    args = ap.parse_args()

    if args.dry_run:
        global _LOG_TO_FILE
        _LOG_TO_FILE = False

    paths = bundle_paths()
    if not paths:
        log("no claude-code webview bundles found "
            "(is the extension installed? check the dirs in candidate_ext_dirs)")
        return 0

    verb = "restore" if args.restore else "patch"
    changed = 0
    errors = 0
    for path in paths:
        result = restore_one(path, args.dry_run) if args.restore else apply_one(path, args.dry_run)
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
        log("FAILED: one or more bundles did not patch as expected (see above)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
