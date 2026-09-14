r"""Install, watch the game start, and try the next route when nothing loaded.

The tool has always stopped at the same place: it writes the files, says
what it wrote, and the person is on their own from there. Two classes of
report come straight out of that gap - "the install stopped part way" and
"nothing we wrote ever loaded" are 32 of the 87 reports in the corpus - and
both were answerable at the time, by the machine, in about a minute.

This is that minute. One pass is:

    install the route -> start the game (or ask, when this tool may not) ->
    wait for the process and let it settle -> read its module list

and the module list decides. Our dxgi.dll in the process means the chain is
in and the person can play; our dxgi.dll beside the game while System32's is
the one loaded means this route cannot work here, however many times it is
installed - so the next route is tried without anybody having to know that.

What it deliberately does NOT do:

  * decide whether the picture is better. That needs frames, a log and
    somebody looking at the screen; "did it work?" answers it afterwards.
  * start a game with anti-cheat, or a launcher executable. The first can
    read a started process as tampering, the second starts the wrong thing.
  * keep going forever. Three routes, then it stops and says so - a loop
    that reinstalls all night is not autopilot, it is a fault.

Nothing here writes into a game folder: the installs are `installer.install`
as the window runs it, and the watching is `watch`, which only reads.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import anticheat, community, installer, log, pe, watch

# Three, and the first one is the route the tool recommended. A fourth try
# has never rescued a game in the corpus, and every attempt costs a download,
# an install and a launch of somebody's game.
MAX_ATTEMPTS = 3

# How long to wait for the game to appear before giving up on this pass.
# A cold start off a hard disk with a launcher in front of it is slow.
START_SECONDS = 300.0


@dataclass
class Attempt:
    """One route, from install to what the process had loaded."""
    route: str
    installed: bool = False
    started: bool = False
    ours: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    elsewhere: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def loaded(self) -> bool:
        return bool(self.ours)


@dataclass
class Outcome:
    attempts: list[Attempt] = field(default_factory=list)
    route: str = ""
    ok: bool = False
    stopped: str = ""

    @property
    def tried(self) -> list[str]:
        return [a.route for a in self.attempts]


def plan(first: str, offer: list[str], data: dict | None = None,
         game=None, limit: int = MAX_ATTEMPTS) -> list[str]:
    """The routes to try, in order, starting with the recommended one.

    Only routes this game is actually offered: naming one that is not in the
    dropdown is #148's shape, and installing one would be worse. What other
    people's results say goes second, so a route that rescued this game
    elsewhere is tried before the rest of the list.
    """
    out = [first] if first and first in (offer or [first]) else []
    if data is not None and game is not None:
        try:
            said = community.next_route(data, game, out[0] if out else "",
                                        list(offer or []))
        except Exception:
            said = ""
        for name in (offer or []):
            if name not in out and said and f" {name} route" in said:
                out.append(name)
    for name in (offer or []):
        if name not in out:
            out.append(name)
    return out[:max(1, limit)]


def may_start(game) -> tuple[bool, str]:
    """Whether this tool may start the game itself, and why not when it may not.

    Never a guess dressed as a yes: when the answer is no the person is told
    what to press, which is what they would have done anyway.
    """
    exe = getattr(game, "exe", None)
    if exe is None:
        return False, "this game has no executable picked"
    try:
        found = anticheat.detect(Path(game.install_dir), Path(game.folder))
    except Exception:
        found = None
    if found is not None and found.present:
        return False, (f"{found.summary} is in this folder ("
                       f"{', '.join(found.evidence[:2])}) - an anti-cheat can "
                       f"read a game started by another program as tampering, "
                       f"so start it yourself the way you always do")
    try:
        if pe.launcher_like(Path(exe)):
            return False, (f"{Path(exe).name} is a launcher, not the game - "
                           f"starting it would start the wrong thing")
    except Exception:
        pass
    src = str(getattr(game, "source", "") or "")
    if src and src.lower() not in ("manual", "emulator"):
        return True, (f"{src} game: it starts from the executable here, but "
                      f"if {src} wants to own the launch, start it there "
                      f"instead - the watching is the same either way")
    return True, ""


def start(game) -> tuple[bool, str]:
    """Start the game. (started, what to say about it.)"""
    ok, why = may_start(game)
    if not ok:
        return False, why
    exe = Path(game.exe)
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent),
                         close_fds=True)
        return True, why
    except Exception as e:                      # a store stub, a permission
        log.write(f"autopilot: could not start {exe.name}: {e}", "warn")
        return False, (f"{exe.name} would not start from here ({e}) - start "
                       f"it the way you normally do and this carries on")


class Hooks:
    """Everything here that touches the world, so a test can hand in its own.

    Plain instance attributes rather than a dataclass: a function stored as
    a CLASS attribute is a descriptor, so `hooks.install(...)` would arrive
    with the Hooks object as its first argument.
    """

    def __init__(self, install=None, wait=None, start=None, log=None,
                 stop=None, seconds: float = START_SECONDS):
        self.install = install or installer.install
        self.wait = wait or watch.wait_for
        self.start = start or globals()["start"]
        self.log = log or (lambda text, kind="": None)
        self.stop = stop or (lambda: False)
        self.seconds = seconds


def _files(root: Path) -> tuple[list[str], str]:
    man = installer._previous_manifest(root) or {}
    return list(man.get("files") or []), str(man.get("exe") or "")


def attempt(game, opt, route: str, hooks: Hooks) -> Attempt:
    """One route: install it, get the game up, read what it loaded."""
    a = Attempt(route=route)
    hooks.log(f"> {route}: installing", "head")
    rep = hooks.install(game, replace(opt, path=route))
    a.installed = bool(rep is None or getattr(rep, "complete", True))
    if not a.installed:
        a.note = "the install did not finish"
        return a
    root = Path(game.install_dir)
    ours, exe = _files(root)

    started, why = hooks.start(game)
    a.note = why
    if started:
        hooks.log(f"  started {Path(game.exe).name} - watching", "")
    else:
        hooks.log(f"  start the game now - {why or 'watching for it'}", "warn")

    seen = hooks.wait(root, ours, exe, seconds=hooks.seconds,
                      tick=lambda _s, _p: not hooks.stop())
    if not seen:
        a.note = a.note or "the game did not start"
        return a
    a.started = True
    for s in seen:
        a.ours += list(s.ours)
        a.missing += list(s.missing)
        a.elsewhere += list(s.elsewhere)
    return a


def run(game, opt, routes: list[str], hooks: Hooks | None = None) -> Outcome:
    """Try each route in turn until the game has our files in it."""
    hooks = hooks or Hooks()
    out = Outcome()
    for route in routes[:MAX_ATTEMPTS]:
        if hooks.stop():
            out.stopped = "stopped"
            return out
        a = attempt(game, opt, route, hooks)
        out.attempts.append(a)
        if a.loaded:
            out.ok, out.route = True, route
            hooks.log(f"  {route}: {', '.join(sorted(set(a.ours))[:3])} "
                      f"loaded in the game", "ok")
            out.stopped = "loaded"
            return out
        if not a.started:
            out.stopped = a.note or "the game was never seen running"
            return out                          # nothing to learn from a rerun
        if a.elsewhere:
            hooks.log(f"  {route}: the game loaded {a.elsewhere[0]} from "
                      f"somewhere else, not ours", "warn")
        else:
            hooks.log(f"  {route}: the game ran and loaded none of our files",
                      "warn")
    out.stopped = "every route tried"
    return out


def summary(out: Outcome) -> str:
    """One line for the window, and for the person who has to decide."""
    if out.ok:
        return (f"The {out.route} route is loaded in the game. Play for a "
                f"few minutes, then press 'did it work?'.")
    if not out.attempts:
        return "Nothing was tried."
    last = out.attempts[-1]
    if not last.started:
        return f"Stopped: {out.stopped}."
    return (f"Tried {', '.join(out.tried)} - the game ran each time and "
            f"loaded none of what was written. Press 'report a bug': the "
            f"module list is in the report and it says what got there first.")
