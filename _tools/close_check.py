r"""Can a person get out of everything this window opens?

    python _tools\close_check.py

2.0.0 shipped a question nobody could close (#263). No check could see it:
the suite proved the handler, the lint proved the drawing, and neither
opened the thing and tried to leave. This does exactly that, on the real
window, with real events.

For every overlay the window can put up - the three kinds of question, the
menus, a toast - it tries each way out that overlay promises:

    esc         Escape pressed on the MAIN window (where the focus usually
                is, not on the card the code happens to bind)
    outside     a real click on the dim, or on the page behind a menu
    control     the overlay's own way out: ok, cancel, the close glyph

and it checks, while the overlay is up, that nothing can hide it: a window
of its own must be a child of what grabs the clicks, and must sit in front
of the window that opened it. That pair is what #263 really was.

A way out that an overlay does not promise is not checked (a toast has no
Escape). Anything that does not close is printed as NOT CLOSED and makes
the exit code 1. Nothing is written outside a temporary folder; the network
is off (see ui_sandbox.py).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_sandbox import Sandbox   # noqa: E402

BAD: list[str] = []


def say(what: str, way: str, closed: bool, note: str = "") -> None:
    mark = "ok      " if closed else "NOT CLOSED"
    print(f"  {mark}  {what} - {way}" + (f"   ({note})" if note else ""))
    if not closed:
        BAD.append(f"{what}: {way}")


# --------------------------------------------------------------- questions
def dialog_ways(sb: Sandbox, app, open_it, what: str) -> None:
    """Open a question three times and leave it a different way each time."""
    root = app.shell.root
    for way in ("esc", "outside", "control"):
        seen: dict = {}

        def probe(way=way, seen=seen, tries=[0]):
            d = app.shell.dialog
            if d is None:
                if tries[0] < 200:
                    tries[0] += 1
                    root.after(50, lambda: probe())
                return
            # nothing can hide it: the grab covers the card (it is a child of
            # what holds the grab), and both windows are owned by the window
            # that opened them, so Windows keeps them over it
            seen["covered"] = (d.card.winfo_parent() == str(d.scrim)
                               and d.scrim.grab_status() == "local")
            seen["front"] = bool(d.card.winfo_ismapped()) and all(
                str(w.wm_transient()) == str(root) for w in (d.scrim, d.card))
            if way == "esc":
                root.focus_force()
                root.update()
                root.event_generate("<Escape>")
                root.update()
                if not d.done.get():
                    root.event_generate("<Escape>")     # a field clears itself first
            elif way == "outside":
                d.scrim.event_generate("<Button-1>", x=4, y=4)
            else:
                click_text(d.card.winfo_children()[0], ("ok", "cancel", "keep", "save"))
            # a control runs its command once the mouse button is up and the
            # event loop has come round (Kit.when_up), so this waits for it
            end = time.monotonic() + 2.0
            while time.monotonic() < end and not d.done.get():
                root.update()
                time.sleep(0.01)
            seen["closed"] = bool(d.done.get())
            if not d.done.get():
                d._finish(False)

        root.after(150, probe)
        open_it()
        sb.pump(root, 0.1)
        if way == "esc":
            say(what, "stays in front, grab covers the card", bool(seen.get("covered")) and bool(seen.get("front")),
                f"covered={seen.get('covered')} front={seen.get('front')}")
        say(what, way, bool(seen.get("closed")))


def click_text(canvas, labels) -> bool:
    """A real click in the middle of the first item whose text is in `labels`."""
    for item in canvas.find_all():
        if canvas.type(item) != "text":
            continue
        if str(canvas.itemcget(item, "text")).strip().lower() in labels:
            x1, y1, x2, y2 = canvas.bbox(item)
            x, y = int((x1 + x2) / 2), int((y1 + y2) / 2)
            canvas.event_generate("<Motion>", x=x, y=y)
            canvas.event_generate("<ButtonPress-1>", x=x, y=y)
            canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
            return True
    return False


# ------------------------------------------------------------------- menus
def menu_ways(sb: Sandbox, app, open_it, what: str) -> None:
    root, kit = app.shell.root, app.shell.kit
    c = app.shell.content
    for way in ("esc", "outside"):
        kit.close_all()
        sb.pump(root, 0.1)
        open_it()
        sb.pump(root, 0.2)
        if kit.top() is None:
            say(what, way, False, "it never opened")
            continue
        if way == "esc":
            # a person's window has the keyboard; this one is invisible and
            # never got it, and a key event with no focus reaches nothing
            root.focus_force()
            sb.pump(root, 0.1)
            root.event_generate("<Escape>")
        else:
            # the corner of the page, well away from any menu
            c.event_generate("<Motion>", x=6, y=6)
            c.event_generate("<ButtonPress-1>", x=6, y=6)
            c.event_generate("<ButtonRelease-1>", x=6, y=6)
        sb.pump(root, 0.35)
        say(what, way, kit.top() is None)
    kit.close_all()


def closing_answers_it() -> None:
    """The last way out: the window itself goes.

    A question blocks in its own event loop, so when the window is destroyed
    under it - the tray's Quit, Windows shutting down - nothing is left to
    write the answer it waits for. That left python.exe spinning on a dead
    interpreter for ever, and every later launch met the "already open"
    guard. This opens one and pulls the window out from under it.
    """
    import threading
    sb = Sandbox(prefix="close_check_shut_")
    app = sb.app(scale=1.0, size=(900, 600), visible=False)
    root, sh = app.shell.root, app.shell
    done: list = []
    # a watchdog that does not depend on the thing under test
    stuck = threading.Timer(25.0, lambda: done or print("  the wait never returned", flush=True))
    stuck.daemon = True
    stuck.start()
    root.after(400, root.destroy)
    out = sh.ask("uninstall", "Remove everything this tool put in the game?", "uninstall", "keep")
    done.append(out)
    stuck.cancel()
    say("a question", "the window closing", True, f"answered {out!r}")
    sb.close()


def main() -> int:
    sb = Sandbox(prefix="close_check_")
    app = sb.app(scale=1.0, size=(1400, 900), visible=False)
    root = app.shell.root
    sh = app.shell
    try:
        print("questions")
        dialog_ways(sb, app, lambda: sh.info("driver 616.92", "what this driver does"), "info")
        dialog_ways(sb, app, lambda: sh.ask("uninstall", "Remove everything?", "uninstall", "keep",
                                            danger=True), "ask")
        dialog_ways(sb, app, lambda: sh.ask_text("profile", "a name for these settings", "mine"),
                    "ask_text")

        print("menus")
        g = sb.game("Close Check", installed=True)
        app.games = [g]
        sh.show("library")
        app.refresh("library")
        sb.pump(root, 0.4)
        page = sh.pages["library"]
        menu_ways(sb, app, page.view_menu, "library: view")
        menu_ways(sb, app, page.scan_menu, "library: scan")
        from types import SimpleNamespace
        menu_ways(sb, app, lambda: page._card_menu(SimpleNamespace(x=60, y=200), g), "library: a game's menu")
        print("toast")
        sh.toast("the watcher", "a game closed", timeout=0)
        sb.pump(root, 0.5)
        shut = [t for t, (kind, label) in sh.kit.registry.items()
                if kind == "link" and not label and sh.content.find_withtag(t)]
        hit = bool(shut) and sb.click(sh.content, shut[-1])
        sb.pump(root, 0.6)
        say("toast", "control", not [x for x in sh.kit.layers if x.tag.startswith("toast")],
            "" if hit else "no way out drawn on it")
    finally:
        sb.destroy(root)
        sb.close()
    print("the window itself")
    closing_answers_it()
    print()
    if BAD:
        print(f"{len(BAD)} way(s) out do not work:")
        for b in BAD:
            print("   -", b)
        return 1
    print("every overlay closes every way it promises")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
