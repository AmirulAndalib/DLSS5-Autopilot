r"""Install every route this tool offers into the games on THIS machine, one
by one, and say what came of each.

    python _tools\route_probe.py                 every game in the library
    python _tools\route_probe.py --game "Ghost"  only games whose name matches
    python _tools\route_probe.py --route feeder  only that route
    python _tools\route_probe.py --keep          leave the last install in place
    python _tools\route_probe.py --play          START each game and read what
                                                 it really loaded

The suites prove the code; they never write into a real game. The owner's
rule since 2026-09-17 is that a release is tried route by route on his own
games first - 2.0.0 shipped with MGS V's DXVK transport silently off, and one
real install would have shown it.

For each game and route it runs the real installer, reads the report, then
takes the install back out again, so a folder ends the run as it began (a
game that had our install before the run keeps whatever was there: the probe
refuses to touch a folder that already has one unless --force).

With `--play` it goes further: it starts the game the way the autopilot
does, waits for it, reads the running process's module list and says whether
OUR files are in it and whether anything shadowed them, then closes the
game and takes the install out. That is the difference between "the files
are on disk" and "the game loaded them" - the fault MGS V had for a whole
release.

What even that cannot say is whether the picture got better: a frame on the
screen is the owner's eye, not a check. The table prints "loaded" where the
files are in the process and "play it" where only the disk was verified.

Nothing runs against a game that is open, or one with anti-cheat.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import anticheat, dlss, games, gpu, installer, library, log  # noqa: E402


def rows(match: str | None) -> list:
    """The library, read by the library's own loader.

    Hand-rolling this lost three things that decide where files go: the
    recorded install root (an install would land beside the executable
    instead - #56's shape), `kind`, so a video-player entry was treated as a
    game, and any API set by hand since the last save. This writes into real
    game folders; it reads them the way the window does.
    """
    # _from_json, not a hand-rolled copy of it, and not library.load():
    # that one is version-gated and answers None the moment this build's
    # version differs from the one that wrote the cache - which is always,
    # the day of a release.
    try:
        data = json.loads(Path(library.FILE).read_text(encoding="utf8"))
    except OSError:
        return []
    found = []
    for d in (data.get("games") if isinstance(data, dict) else data) or []:
        try:
            found.append(library._from_json(d))
        except Exception:
            continue
    out = []
    for g in found:
        if getattr(g, "kind", "") == "video":
            continue
        if match and match.lower() not in g.name.lower():
            continue
        out.append(g)
    return out


def skip_reason(g) -> str:
    if g.exe is None or not g.exe.is_file():
        return "no executable on disk"
    if g.api in ("?", ""):
        return "the API is unknown - the tool offers no route"
    ac = anticheat.detect(g.install_dir, g.folder)
    # the finding is an object either way: what matters is whether it names a
    # product (an empty Finding read as "anti-cheat" and skipped every game)
    found = list(getattr(ac, "products", []) or [])
    if found:
        return "anti-cheat (" + ", ".join(str(x) for x in found[:2]) + ")"
    if _running(g.exe.name):
        return "the game is running"
    ok, why = installer.check_supported(g)
    if not ok:
        return why or "not supported"
    return ""


def _running(exe_name: str) -> bool:
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return False
    return exe_name.lower() in out.lower()


def probe(g, route: str, keep: bool, play: bool = False) -> tuple[str, str]:
    """(verdict, detail) for one game on one route."""
    opt = installer.Options(path=route, dxvk=bool(installer.wants_dxvk(g)))
    lines: list[str] = []
    if play:
        return played(g, opt, route, keep)
    try:
        rep = installer.install(g, opt, on_log=lambda t: lines.append(str(t).strip()))
    except installer.InstallError as e:
        return "install refused", str(e)[:150]
    except Exception as e:                       # noqa: BLE001 - the probe reports, never raises
        return "CRASHED", f"{type(e).__name__}: {e}"[:150]
    wrote = len(getattr(rep, "written", []) or [])
    notes = "; ".join(str(n) for n in (getattr(rep, "notes", []) or []))[:120]
    verdict = "installed - play it" if wrote else "wrote nothing"
    if not keep:
        try:
            installer.uninstall(g, on_log=lambda t: lines.append(str(t).strip()))
        except Exception as e:                   # noqa: BLE001
            verdict += f" (BUT uninstall raised {type(e).__name__})"
    return verdict, f"{wrote} files. {notes}"


def played(g, opt, route: str, keep: bool) -> tuple[str, str]:
    """Install, start the game, read what the running process loaded.

    This is the autopilot's own pass with one route in it, so what is being
    checked is the thing people actually press - not a copy of it.
    """
    from core import autopilot
    said: list[str] = []
    # 90 seconds, not the five minutes a person gets: a probe that waits
    # five minutes per route on eight games is a probe nobody runs
    hooks = autopilot.Hooks(log=lambda t, kind="": said.append(str(t).strip()),
                            seconds=90.0)
    try:
        out = autopilot.run(g, opt, [route], hooks)
    except installer.InstallError as e:
        return "install refused", str(e)[:150]
    except Exception as e:                       # noqa: BLE001
        return "CRASHED", f"{type(e).__name__}: {e}"[:150]
    tries = list(getattr(out, "attempts", None) or [])
    a = tries[0] if tries else None
    if a is None:
        return "no attempt", "; ".join(said[-2:])[:150]
    if not a.installed:
        return "install failed", (a.why or "; ".join(said[-2:]))[:150]
    if not a.started:
        return "never started", (a.note or a.why or "the game did not come up")[:150]
    if a.elsewhere:
        return "SHADOWED", f"ours loaded but so did {', '.join(a.elsewhere[:3])}"
    if a.loaded:
        detail = f"in the process: {', '.join(a.ours[:4])}"
    else:
        detail = f"not in the process. missing: {', '.join(a.missing[:4]) or '(none named)'}"
    verdict = "loaded" if a.loaded else "NOT LOADED"
    # the game this probe started is closed again before anything is taken
    # out: Windows refuses to replace a DLL a running game has mapped in,
    # and the game was only ever opened to read its module list
    closed = _close(g)
    if not closed:
        verdict += " (the game would not close)"
    if not keep and closed:
        try:
            installer.uninstall(g, on_log=lambda t: said.append(str(t).strip()))
        except Exception as e:                   # noqa: BLE001
            verdict += f" (BUT uninstall raised {type(e).__name__})"
    return verdict, detail[:150]


def _close(g, seconds: float = 45.0) -> bool:
    """Ask the game to close, then insist. True when it is gone."""
    import subprocess
    name = Path(g.exe).name if g.exe else ""
    if not name:
        return True
    for force in (False, True):
        try:
            subprocess.run(["taskkill", "/IM", name] + (["/F"] if force else []),
                           capture_output=True, text=True, timeout=30)
        except Exception:
            pass
        end = time.monotonic() + (seconds / 2)
        while time.monotonic() < end:
            if not _running(name):
                return True
            time.sleep(1.0)
    return not _running(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game")
    ap.add_argument("--route")
    ap.add_argument("--keep", action="store_true", help="leave the last install in place")
    ap.add_argument("--force", action="store_true", help="also touch folders that already have an install")
    ap.add_argument("--play", action="store_true",
                    help="start each game and read what it really loaded")
    a = ap.parse_args()
    log.start("route_probe")
    card, sm = gpu.detect()
    drv = gpu.driver_version()
    print(f"card: {card}  {gpu.label(sm)}  driver {drv}")
    table: list[tuple] = []
    for g in rows(a.game):
        why = skip_reason(g)
        if why:
            table.append((g.name, "-", "skipped", why))
            continue
        if g.installed and not a.force:
            table.append((g.name, "-", "skipped", "our install is already in this folder (--force)"))
            continue
        sup = dlss.detect(g.install_dir, g.folder, g.api, g.bitness or 0, sm, driver=drv)
        offered = [r for r in (sup.options or []) if not a.route or r == a.route]
        if not offered:
            table.append((g.name, "-", "skipped", "no route offered for this game"))
            continue
        for route in offered:
            started = time.monotonic()
            verdict, detail = probe(g, route, a.keep and route == offered[-1], play=a.play)
            table.append((g.name, route, verdict, f"{detail}  [{time.monotonic() - started:.0f}s]"))
            print(f"  {g.name[:34]:36} {route:11} {verdict:22} {detail[:90]}")
    print()
    print("=" * 78)
    print(f"{'game':30} {'route':11} {'what happened':24}")
    print("=" * 78)
    for name, route, verdict, detail in table:
        print(f"{name[:29]:30} {route:11} {verdict:24} {detail[:60]}")
    bad = [r for r in table if r[2].startswith("CRASHED") or "wrote nothing" in r[2]
           or "BUT uninstall" in r[2] or "would not close" in r[2]
           or r[2] in ("NOT LOADED", "SHADOWED", "install failed", "never started", "no attempt")]
    print()
    if bad:
        print(f"{len(bad)} route(s) to look at by hand:")
        for r in bad:
            print("   -", r[0], r[1], r[2], r[3][:80])
        return 1
    print("every route offered installed and came back out again."
          + (" Each one was started and had our files in the process." if a.play
             else " What is left is playing them."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
