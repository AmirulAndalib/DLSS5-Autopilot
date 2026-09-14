r"""The games that do not work, grouped by the shape they share.

    python _tools\stuck_games.py            the corpus in _tools\reports
    python _tools\stuck_games.py --json     the same, machine-readable

`brain.py` answers "which routes work" from the shared results. `state.py`
answers "what does the tool SAY" from the corpus. Neither answers the
question that decides what to build next:

    the games that do not work - what do they have in common, and who has
    to fix each kind?

So this reads every saved report and puts it at the point of the chain its
verdict describes: installed, loaded, a contract built, frames evaluated,
frames on screen. Where a game falls says who can act - this tool, the
upstream add-on, NVIDIA's runtime, or the person at the keyboard - and a
group of nine with the same shape is a batch of games that come back
together.

The verdicts are matched by their own text, not by a guess at what they
might say: there are 21 of them in the corpus and they are listed below.
A verdict that is not in the list comes out as "unmapped" and is meant to
be added here, not silently bucketed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

REPORTS = HERE / "reports"

# (stage, who can fix it, the verdicts that mean it - matched on the start
# of the printed verdict). In chain order, and every entry is a real
# verdict string from core/diagnose.py.
CHAIN = (
    ("1 the install stopped", "us", (
        "The install never finished",
        "The install crashed",
        "The install stopped",
        "The drive was full",
        "Nothing is installed in this folder",
    )),
    ("2 a file went missing after it", "the person's antivirus", (
        "ReShade's",
        "Files the install wrote are gone",
        "The motion-vector shader was removed",
    )),
    ("3 nothing of ours loaded", "us", (
        "Not started since the install",
        "Not run yet, or OptiScaler never loaded",
        "DXVK ran and ReShade did not",
        "It started, and nothing here recorded the session",
        "The install went beside a launcher",
        "is running and has loaded nothing from this folder",
    )),
    ("4 the game refused the hook", "upstream", (
        "The game refused OptiScaler's swapchain",
        "The game refused the swapchain",
    )),
    ("5 loaded, the feed never got going", "upstream", (
        "Inconclusive - the feed did not get far enough",
        "Inconclusive - the add-on attached but built nothing",
        "Remix ran; the neural pass was never even attempted",
        "No Remix runtime",
        "The Remix runtime here has no neural pass",
    )),
    ("6 set up, not switched on", "the person", (
        "Set up correctly, but not switched on yet",
        "Loaded and set up; no neural frame yet",
    )),
    ("7 loaded, and we cannot see", "us", (
        "Inconclusive - open the overlay",
        "Add-ons loaded. Confirm in",
    )),
    ("8 the add-on crashed", "upstream", (
        "The feed crashed after starting",
        "The crash is in the",
    )),
    ("9 the model refused", "upstream", (
        "OptiScaler loaded, but the model refused or failed",
    )),
    ("10 the driver's runtime", "NVIDIA", (
        "Driver 616.64+ faults",
        "The driver has no DLSS 5 entry point",
        "Every DLSS evaluate faults",
    )),
    ("0 working", "-", ("Working",)),
)


def stage(verdict: str) -> tuple[str, str]:
    if not verdict.strip():
        return "no verdict in the report", "-"
    for name, who, starts in CHAIN:
        for s in starts:
            if s.lower() in verdict.lower():
                return name, who
    return "unmapped: " + verdict[:40], "?"


def header(text: str) -> dict:
    out: dict = {}
    for k in ("version", "gpu", "game", "exe", "arch/api", "route"):
        m = re.search(r"^- " + re.escape(k) + r":\s*(.+)$", text, re.M)
        if m:
            out[k] = m.group(1).strip()
    m = re.search(r"^\*\*Diagnosis\*\*:\s*(.+)$", text, re.M)
    out["verdict"] = m.group(1).strip() if m else ""
    m = re.search(r"driver\s+([\d.]+)", out.get("gpu", ""))
    out["driver"] = m.group(1) if m else "?"
    api = re.search(r"(DX9|DX10|DX11|DX12|Vulkan|OpenGL)", out.get("arch/api", ""))
    out["api"] = api.group(1) if api else "?"
    out["bits"] = "32" if "32-bit" in out.get("arch/api", "") else "64"
    return out


def rows() -> list[dict]:
    out = []
    for p in sorted(REPORTS.glob("*.txt")):
        text = p.read_text(encoding="utf8", errors="replace").replace("\r\n", "\n")
        h = header(text)
        h["issue"] = p.stem.lstrip("0") or p.stem
        h["stage"], h["who"] = stage(h["verdict"])
        out.append(h)
    return out


def _who(rows_: list[dict], name: str, key) -> str:
    return ", ".join(sorted({f"#{r['issue']}" for r in rows_
                             if (key(r) or "?") == name},
                            key=lambda s: int(s[1:]))[:6])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    data = rows()
    said = [r for r in data if r["verdict"]]
    stuck = [r for r in said if not r["stage"].startswith("0 ")]
    if a.json:
        print(json.dumps(stuck, indent=1))
        return 0

    print("=" * 78)
    print(f"{len(stuck)} REPORTS WHERE THE GAME DID NOT WORK")
    print(f"({len(said)} of {len(data)} reports carry a verdict; the rest are "
          f"from before the template printed one)")
    print("=" * 78)

    def block(title: str, key, note: str = "") -> None:
        c = Counter(key(r) or "?" for r in stuck)
        print(f"\n  by {title}" + (f"   ({note})" if note else ""))
        for name, n in c.most_common():
            share = 100 * n / max(1, len(stuck))
            print(f"    {n:3}  {share:3.0f}%  {name:<34} "
                  f"{_who(stuck, name, key)}")

    block("where the chain stopped", lambda r: r["stage"],
          "in chain order")
    block("who can fix that", lambda r: r["who"])
    block("graphics api", lambda r: f"{r['api']} {r['bits']}-bit")
    block("route", lambda r: r["route"])
    block("driver", lambda r: r["driver"])

    print("\n  the shapes (api + where it stopped), biggest first")
    pairs = Counter((f"{r['api']} {r['bits']}-bit", r["stage"]) for r in stuck)
    for (api, st), n in pairs.most_common(14):
        if n < 2:
            continue
        who = ", ".join(sorted({f"#{r['issue']}" for r in stuck
                                if f"{r['api']} {r['bits']}-bit" == api
                                and r["stage"] == st},
                               key=lambda s: int(s[1:]))[:6])
        print(f"    {n:3}  {api:<13} {st:<32} {who}")

    print("\n  games reported more than once")
    by_game: dict[str, list[dict]] = defaultdict(list)
    for r in stuck:
        by_game[r.get("game") or "?"].append(r)
    for name, rs in sorted(by_game.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < 2:
            continue
        print(f"    {len(rs):3}  {name[:36]:<36} "
              f"{', '.join(sorted({x['stage'] for x in rs}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
