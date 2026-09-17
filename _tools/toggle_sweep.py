r"""Every switch, on and off, and what it actually changed on disk.

    python _tools\toggle_sweep.py                  every route, every switch
    python _tools\toggle_sweep.py --route feeder   one route
    python _tools\toggle_sweep.py --api DX11       one API

A switch that draws, saves and then changes nothing in the game folder is
worse than a missing one: the person ticks it, believes it, and plays
without it. Nothing checked that, so this does - by installing twice into a
scratch folder, once with the switch off and once on, and comparing what
was written: the file list, and the text of every config the install wrote
(ReShade.ini, dlss5-feed.cfg, dlss5-bridge.cfg, OptiScaler.ini, the layer
manifests).

It writes into a temporary folder, never into a game. Two switches reach
outside it by their nature - the VR and Vulkan layers are registered for the
user, not for a game - so the sweep reads those registrations too, and
leaves them as it found them by uninstalling each side.

Each row is printed as:

    feeder   DX11  dxvk          8 file(s), 2 line(s) changed
    feeder   DX11  mfg           NOTHING CHANGED        <- worth a look

"NOTHING CHANGED" is not always a bug (a switch can be a no-op for a card
or a game that does not reach it) but it is always a question, and the exit
code is 1 so the gate stops and somebody answers it.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import dlss, games, gpu, installer, log  # noqa: E402

# The scratch game's executable. It has to be a REAL binary whose import
# table names one of the ASI loader slots (version.dll and the rest), or the
# frame-generation switch has nowhere to put its loader and reads as a switch
# that does nothing. The suite's own fixture is the same file.
import os  # noqa: E402

X64 = Path(os.environ.get("DLSS5_TEST_X64",
                          r"C:\Users\Mustafa\Downloads\dlss5-feed-host64.exe"))

# The switches to sweep, and where each one applies. Read from the window's
# own rules (core/ui/ctl_game.shown_setting) so the two cannot drift apart.
SWITCHES = (
    ("dxvk", ("DX11",), (dlss.NATIVE, dlss.BRIDGE, dlss.FEEDER)),
    # D3D12 and Vulkan only, and only for a game that ships DLSS frame
    # generation of its own (mfg.applies) - the scratch game below ships one
    ("mfg", ("DX12",), (dlss.NATIVE, dlss.BRIDGE, dlss.FEEDER, dlss.RENODX)),
    ("fg", ("DX12",), (dlss.OPTI,)),
    ("vr", ("DX11", "DX12"), (dlss.NATIVE, dlss.BRIDGE, dlss.FEEDER, dlss.RENODX)),
    # not on optiscaler: its install cannot act on the game's own DLSS file
    # (README, "Keeping a game's DLSS up to date"), and the window hides the
    # row there, so a sweep that asked for it was asking the wrong question
    ("keep_game_dlss", ("DX11", "DX12"), (dlss.NATIVE, dlss.BRIDGE, dlss.FEEDER)),
)
CONFIGS = ("ReShade.ini", "dlss5-feed.cfg", "dlss5-bridge.cfg", "OptiScaler.ini",
           "standalone-dlssnr.cfg")


def scratch(api: str, root: Path, fresh: bool = False) -> "games.Game":
    d = root / f"game_{api}"
    if fresh and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    exe = d / "Game.exe"
    if not exe.is_file():
        if not X64.is_file():
            raise SystemExit(
                f"the scratch executable is missing: {X64}\n"
                f"Set DLSS5_TEST_X64 to a real 64-bit exe that imports one of "
                f"{', '.join(__import__('core.mfg', fromlist=['mfg']).LOADER_NAMES[:3])}...")
        shutil.copyfile(X64, exe)
    # a game that ships DLSS of its own: 'keep the game's own' has something
    # to keep, and the frame-generation switch something to unlock. Without
    # them both switches are no-ops and the sweep reads that as a fault.
    for name in ("nvngx_dlss.dll", "nvngx_dlssg.dll"):
        p = d / name
        if not p.is_file():
            shutil.copyfile(exe, p)
    return games.Game(name=f"Scratch {api}", folder=d, exe=exe, bitness=64, api=api,
                      api_detected=api, source="Manual", candidates=[exe])


def picture(folder: Path) -> tuple[set[str], dict[str, str]]:
    """What is in the folder: the file names, and the text of each config.

    Plus what an install writes OUTSIDE the folder - the shared Vulkan and
    OpenXR layer files and their registrations. The VR switch touches
    nothing in the game folder at all, which read as "does nothing" until
    this looked where it really writes.
    """
    names = set()
    for p in folder.rglob("*"):
        if p.is_file():
            names.add(str(p.relative_to(folder)).replace("\\", "/"))
    texts = {}
    for name in CONFIGS:
        for p in folder.rglob(name):
            try:
                texts[str(p.relative_to(folder))] = p.read_text(encoding="utf8", errors="replace")
            except OSError:
                pass
    try:
        from core import openxr, vulkan
        d = vulkan.layer_dir()
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file():
                    names.add("(layers)/" + p.name)
        texts["(registered vulkan layers)"] = "\n".join(str(x) for x in vulkan.registrations())
        texts["(registered openxr layers)"] = "\n".join(str(x) for x in openxr.registrations())
    except Exception:
        pass
    return names, texts


def diff(a, b) -> tuple[int, int]:
    """(files that appeared or went, config lines that differ)."""
    (an, at), (bn, bt) = a, b
    files = len(an ^ bn)
    lines = 0
    for key in set(at) | set(bt):
        first = (at.get(key) or "").splitlines()
        second = (bt.get(key) or "").splitlines()
        lines += len(set(first) ^ set(second))
    return files, lines


class Refused(Exception):
    """One side of the comparison never installed, so there is nothing to
    compare. Counting it as "the switch changed 23 files" is how a sweep
    goes green on a failure."""


def one(g, route: str, key: str, value: bool, root: Path) -> tuple[set, dict]:
    opt = installer.Options(path=route, **{key: value})
    try:
        installer.install(g, opt, on_log=lambda _t: None)
    except installer.InstallError as e:
        raise Refused(str(e).strip().splitlines()[0] if str(e).strip() else "install refused")
    except Exception as e:                       # noqa: BLE001
        raise Refused(f"{type(e).__name__}: {e}")
    shot = picture(g.install_dir)
    try:
        installer.uninstall(g, on_log=lambda _t: None)
    except Exception as e:                       # noqa: BLE001
        raise Refused(f"uninstall raised {type(e).__name__}")
    return shot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route")
    ap.add_argument("--api")
    a = ap.parse_args()
    log.start("toggle_sweep")
    card, sm = gpu.detect()
    print(f"card: {card}  {gpu.label(sm)}  driver {gpu.driver_version()}")
    root = Path(tempfile.mkdtemp(prefix="toggle_sweep_"))
    quiet: list[tuple] = []
    try:
        for key, apis, routes in SWITCHES:
            for api in apis:
                if a.api and api != a.api:
                    continue
                g = scratch(api, root)
                for route in routes:
                    if a.route and route != a.route:
                        continue
                    sup = dlss.detect(g.install_dir, g.folder, api, 64, sm,
                                      driver=gpu.driver_version())
                    if route not in (sup.options or []):
                        continue
                    # the scratch game is rebuilt for every pair: an install
                    # and uninstall can consume the runtimes it ships, and
                    # every later route was then measured on a poorer folder
                    g = scratch(api, root, fresh=True)
                    try:
                        off = one(g, route, key, False, root)
                        on = one(g, route, key, True, root)
                    except Refused as e:
                        print(f"  {route:11} {api:5} {key:16} NOT MEASURED - {e}")
                        quiet.append((route, api, key, str(e)))
                        continue
                    files, lines = diff(off, on)
                    said = (f"{files} file(s), {lines} line(s) changed" if (files or lines)
                            else "NOTHING CHANGED")
                    print(f"  {route:11} {api:5} {key:16} {said}")
                    if not (files or lines):
                        quiet.append((route, api, key, "nothing changed on disk"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    if quiet:
        print(f"{len(quiet)} switch/route pair(s) to answer:")
        for route, api, key, why in quiet:
            print(f"   - {key} on {route} ({api}): {why}")
        print("Each one is either a switch that does nothing here, or one that "
              "does nothing at all. Answer it before a release.")
        return 1
    print("every switch changed something in the folder, both ways")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
