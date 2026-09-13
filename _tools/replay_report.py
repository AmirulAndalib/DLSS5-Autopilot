r"""Replay a real bug report through the diagnosis, before writing a fix.

Every wrong verdict this tool has given was found the same way: take the
logs out of the report, put them in a folder the way the person had them,
and run `diagnose.analyse()` over it. Reading the rule and reasoning about
it is how the wrong ones got written in the first place.

Two ways in.

**A report pasted into a file.** Save the issue body (the whole thing, with
its ``` blocks) and point at it:

    python _tools\replay_report.py --issue 63 report.txt

It pulls out the version/gpu/route header, the ReShade.log, dlss5-feed.log,
OptiScaler.log and standalone-dlssnr.log blocks, builds a folder that looks
like that install, and prints the verdict the current code would give.

**A log file downloaded from the issue.** GitHub attachments are plain URLs:

    python _tools\replay_report.py --route upstream --reshade ReShade.log
    python _tools\replay_report.py --route feeder --feed dlss5-feed.log \
        --reshade ReShade.log --api DX12 --exe Game.exe

Then the part that matters: **change the code, run it again, and read the
verdict.** If the verdict is right for the wrong reason, it is still wrong -
check which finding fired.

Once it says what it should, copy the log lines into a test in test_all.py.
The reports are the only real inputs this project has; a rule that has never
seen one is a guess.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import diagnose   # noqa: E402

# The report template's own headings, so a pasted issue can be taken apart.
BLOCKS = {
    "ReShade.log": "reshade",
    "dlss5-feed.log": "feed",
    "OptiScaler.log": "opti",
    "standalone-dlssnr.log": "standalone",
}
ADDONS = ("dlss5-feed.addon64", "renodx-dlss5.addon64")


def _blocks(text: str) -> dict:
    """Every ```-fenced block in the report, keyed by the heading above it."""
    out: dict = {}
    for name, key in BLOCKS.items():
        m = re.search(r"\*\*" + re.escape(name) + r"[^\n]*\*\*\s*\n```[^\n]*\n(.*?)```",
                      text, re.S)
        if m and m.group(1).strip() not in ("(none)", ""):
            out[key] = m.group(1)
    return out


def _header(text: str) -> dict:
    """version / gpu / game / exe / arch/api / route out of the report head."""
    out = {}
    for k in ("version", "gpu", "game", "exe", "arch/api", "route"):
        m = re.search(r"^- " + re.escape(k) + r":\s*(.+)$", text, re.M)
        if m:
            out[k] = m.group(1).strip()
    return out


def folder_state(text: str) -> dict | None:
    """What the report says was in the folder, from its own file list.

    The list under "**Files in the folder**" is written by
    `diagnose._presence()` on the reporter's machine, so it is the one piece
    of the report that describes the DISK rather than a log. Until 1.8.2
    this was thrown away and every report was replayed against a folder with
    every file in place and a finished install record - so no replay could
    ever reproduce a quarantined DLL, an uninstalled folder, or a folder the
    tool had never installed into (#43, #194). The measurement said "not
    started since the install" as often as the corpus did, and the reason
    those reports got that answer stayed invisible.

    Returns None when the report has no such list (the older template), so
    those keep the old behaviour: a folder with everything in place.

    Otherwise: {"files": {name: present}, "manifest": bool}. No proxy DLL,
    no add-on, no Vulkan layer and no .trex line in the list means
    `_presence` had nothing to name them from - there was no install record
    in that folder at all.
    """
    m = re.search(r"\*\*Files in the folder\*\*\s*\n(.*?)(?:\n\*\*|\Z)", text, re.S)
    if not m:
        return None
    files: dict[str, bool] = {}
    named = False
    layer: bool | None = None
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        name, _, state = line[2:].partition(":")
        name, state = name.strip(), state.strip()
        # Lines that describe a registration or a folder rather than a file
        # beside the game: they answer "is the install recorded", not "is
        # this file on disk", and there is nothing to create for them.
        if name.lower().startswith(("reshade openxr", "reshade ", ".trex",
                                    "optiscaler build", "runtime flavour",
                                    "the game's own upscaler")):
            if "vulkan layer" in name.lower():
                # "registered" / "NOT REGISTERED": the layer is a registry
                # entry, so this line is the only place a replay can learn
                # what the loader on that machine had.
                layer = not state.upper().startswith("NOT")
                named = True
            else:
                named = named or "registered" in state.lower()
            continue
        if "/" in name and name.split("/")[0].endswith(".trex"):
            named = True
            continue
        files[name] = state.startswith("present") or state.startswith("not written")
        if re.match(r"(dxgi|d3d9|d3d10|d3d11|d3d12|opengl32|winmm|version|"
                    r"dinput8|nvngx)\.dll$", name, re.I) or ".addon" in name.lower():
            named = True
    if not files and not named:
        return None
    proxy = next((n for n in files if re.match(
        r"(dxgi|d3d9|d3d10|d3d11|d3d12|opengl32|winmm|version|dinput8)\.dll$",
        n, re.I)), "")
    if not proxy and (layer is not None or "(vulkan layer)" in files):
        proxy = "(vulkan layer)"                  # diagnose.VULKAN_LAYER
        if layer is None:
            layer = files.get("(vulkan layer)", False)
        files.pop("(vulkan layer)", None)
    return {"files": files, "manifest": named, "proxy": proxy, "layer": layer}


def build(route: str, api: str, exe: str, logs: dict, bitness: int = 64,
          extra_manifest: dict | None = None,
          state: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp(prefix="replay_"))
    proxy = "dxgi.dll"
    files = [proxy] + (list(ADDONS) if route == "feeder" else [])
    on_disk = files + ["ReShade.ini", "nvngx_dlssnr.dll",
                       "reshade-shaders/Shaders/DLSS5_Feed.fx",
                       "reshade-shaders/Shaders/lumenite_Kernel.fx"]
    write_manifest = True
    if state is not None:
        # The report's own list has the last word on both questions: which
        # files were there, and whether the install was recorded at all.
        # What the install WROTE stays the default set - a file the report
        # calls MISSING is one that was written and has since gone, which is
        # exactly what `diagnose._missing_core` is there to notice.
        on_disk = [n for n, there in state["files"].items() if there]
        # No proxy in the list means the install did not write one under a
        # name this can see - guessing dxgi.dll there invents a file that is
        # "missing" and answers the wrong question (#16, #19: both Vulkan).
        proxy = state["proxy"]
        files = sorted(set(state["files"]) | ({proxy} if proxy else set()))
        write_manifest = bool(state["manifest"])
    man = {"version": 1, "complete": True, "exe": exe, "bitness": bitness,
           "api": api, "proxy": proxy, "path": route, "files": files}
    man.update(extra_manifest or {})
    if write_manifest:
        (d / "dlss5-autopilot.json").write_text(json.dumps(man), encoding="utf8")
    for n in on_disk:
        p = d / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"MZ")
    sh = d / "reshade-shaders" / "Shaders"
    sh.mkdir(parents=True, exist_ok=True)
    for key, name in (("reshade", "ReShade.log"), ("feed", "dlss5-feed.log"),
                      ("opti", "OptiScaler.log")):
        if logs.get(key):
            (d / name).write_text(logs[key], encoding="utf8")
    return d


def show(d: Path, label: str) -> None:
    rep = diagnose.analyse(d)
    print("=" * 78)
    print(label)
    print("=" * 78)
    print(f"  ran: {rep.ran}   route: {rep.route or '(none)'}")
    print(f"  VERDICT: {rep.verdict}")
    for f in rep.findings:
        print(f"    [{f.level:4}] {f.title}")
        if f.detail:
            print(f"           {f.detail[:150]}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("report", nargs="?", help="a saved issue body")
    p.add_argument("--issue", default="?")
    p.add_argument("--route", default="feeder")
    p.add_argument("--api", default="DX12")
    p.add_argument("--exe", default="Game.exe")
    p.add_argument("--bitness", type=int, default=64)
    p.add_argument("--reshade"), p.add_argument("--feed"), p.add_argument("--opti")
    p.add_argument("--keep", action="store_true", help="leave the folder behind")
    a = p.parse_args()

    logs, route, api, exe, state = {}, a.route, a.api, a.exe, None
    if a.report:
        text = Path(a.report).read_text(encoding="utf8", errors="replace")
        logs = _blocks(text)
        state = folder_state(text)
        head = _header(text)
        route = head.get("route", route)
        exe = head.get("exe", exe)
        if "arch/api" in head:
            m = re.search(r"(DX9|DX10|DX11|DX12|Vulkan|OpenGL)", head["arch/api"])
            if m:
                api = m.group(1)
            if "32-bit" in head["arch/api"]:
                a.bitness = 32
        print("report header:", ", ".join(f"{k}={v}" for k, v in head.items()) or "(none)")
        print("log blocks found:", ", ".join(logs) or "(none)")
    for key, path in (("reshade", a.reshade), ("feed", a.feed), ("opti", a.opti)):
        if path:
            logs[key] = Path(path).read_text(encoding="utf8", errors="replace")
    if not logs and state is None:
        print("nothing to replay: pass a saved report, or --reshade/--feed/--opti")
        return 2
    if state is not None:
        gone = [n for n, there in state["files"].items() if not there]
        print(f"folder: {len(state['files']) - len(gone)} file(s) present"
              + (f", gone: {', '.join(gone)}" if gone else "")
              + ("" if state["manifest"] else ", NO install record"))

    d = build(route, api, exe, logs, a.bitness, state=state)
    show(d, f"issue #{a.issue}  route={route}  api={api}  exe={exe}")
    if a.keep:
        print(f"\nfolder kept: {d}")
    else:
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
