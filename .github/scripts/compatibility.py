"""Turn the shared results into docs/compatibility.json.

Run by .github/workflows/compatibility.yml. It reads the machine-readable
block the tool writes into each shared result (core/community.py owns the
format and the parser, and this script imports it so the two can never
drift apart), and writes one small aggregate:

    {"generated": "2026-09-09T11:00:00Z",
     "reports": 812,
     "games": {"cyberpunk2077.exe": {
        "name": "Cyberpunk 2077",
        "routes": {"optiscaler": {"worked": 41, "failed": 6}},
        "drivers": {"616.64": {"worked": 3, "failed": 22}},
        "measured": {"optiscaler": {"n": 9, "res": 70, "ms": 6.4,
                                    "fps": 78}}}},
     "by_class": {"DX12/dlss": {"optiscaler": {"worked": 30, "failed": 8}}},
     "by_driver": {"616.92": {"feeder": {"worked": 11, "failed": 32}}}}

`by_class` counts results by the kind of game (graphics api, and whether
it ships DLSS, FSR, XeSS or none of them) and `by_driver` by driver, each
split by route: what the tool knows about a game nobody has reported yet.

The `measured` rows are the middle of what people ran: the work area and
the frame rate they played at, and what grows with the work area cost a
frame (the model alone, or model and feed together on the feeder) - measured
where the route logs it, solved from two sessions where it does not. Only
from results that worked - a session that crashed measured a crash - and
only the median, so one machine with a strange number cannot move the
answer far.

Counts only. No user names, no issue numbers, nothing that ties a row back
to a person - the whole point of the file is that it can be published
without anyone having agreed to be published.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.community import parse            # noqa: E402  the one parser
from core.community import counts           # noqa: E402  and what it cannot see

# Results written before 2.0.5 on a verdict that could not see the outcome
# were filed as "failed" whatever the game did, and are left out as unknown
# (community.counts). These people rewrote the issue's title to say it
# worked while the block said failed; the person who played it outranks the
# tool's reading of it, whichever verdict that was.
SAID_IN_WORDS = {
    414: "worked",      # "It Did Work." / "WORKED FINE" - Arkham Knight, renodx
    388: "worked",      # "God of War -working" - bridge
    307: "worked",      # "work, set to 100% only" - Venus Vacation PRISM, renodx
    257: "worked",      # "It Did Work" - DragonSword, native
    242: "worked",      # "did work but charges me to update" - No Man's Sky, bridge
    222: "worked",      # "inZOI - worked perfectly" - optiscaler
    437: "worked",      # "It appeared to work in game" - Red Dead Redemption 2, upstream
}


def median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def text(value, limit: int) -> str:
    """A string out of an issue body, or "".

    Nothing here was written by the tool: `exe` is used as a dict key and
    then sorted, so a list or a number there ends the run and the published
    file stops being rebuilt for everybody. A 200 000-character game name
    would be published and then printed into the log of everyone who picks
    that game.
    """
    return value.strip()[:limit] if isinstance(value, str) else ""


def number(value, low: float, high: float) -> float | None:
    """A number out of an issue body, or None.

    Everything here is written by whoever opened the issue. JSON has
    Infinity and NaN in it, int(round(inf)) raises, and a game nobody else
    has reported has no second sample to out-vote the first - so one
    hand-written block would end this script and the published file would
    stop being rebuilt for everybody. A value outside the range the tool
    can even produce is not a measurement either.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or not (low <= value <= high):
        return None
    return value

OUT = ROOT / "docs" / "compatibility.json"
API = "https://api.github.com/repos/{repo}/issues"
# The published file is downloaded by every copy of the tool. Anybody can
# open an issue, so the number of games in it is bounded here too.
MAX_GAMES = 5000
# The two tables the recommendation reads (community.class_pick,
# community.driver_note): the same results counted by what the tool knows
# before an install - the class of game, and the driver - each split by
# route, because a driver's rate across all routes is mostly its route mix.
# Keys are checked against the shapes the tool writes; a hand-written block
# with anything else counts for its game and not here. Bounded like MAX_GAMES.
MAX_KEYS = 300
APIS = {"DX8", "DX9", "DX10", "DX11", "DX12", "VULKAN", "OPENGL", "UNKNOWN"}
UPS = {"dlss", "fsr", "xess", "none"}
DRIVER = re.compile(r"^\d{3}\.\d{2}$")
ROUTE = re.compile(r"^[a-z_]{2,20}$")


def bump(table: dict, key: str, route: str, result: str) -> None:
    if not ROUTE.match(route) or (key not in table and len(table) >= MAX_KEYS):
        return
    row = table.setdefault(key, {}).setdefault(route, {"worked": 0, "failed": 0})
    row[result] += 1


def issues(repo: str, token: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while page <= 20:                        # 2000 issues is plenty of head room
        # No label filter: GitHub silently drops ?labels= from a
        # prefilled new-issue URL for anyone without triage rights on the
        # repository, so most results arrive unlabelled. parse() is the
        # filter that matters - it ignores anything without a valid record.
        url = (f"{API.format(repo=repo)}?state=all"
               f"&per_page=100&page={page}")
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "dlss5-autopilot-compatibility",
            "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            batch = json.load(r)
        if not batch:
            break
        out += [i for i in batch if "pull_request" not in i]
        if len(batch) < 100:
            break
        page += 1
    return out


def main() -> int:
    repo = os.environ.get("REPO") or "Kizzuwatnaa/DLSS5-Autopilot"
    token = os.environ.get("GH_TOKEN") or ""
    games: dict[str, dict] = {}
    by_class: dict[str, dict] = {}
    by_driver: dict[str, dict] = {}
    seen_ms: dict[str, dict[str, list]] = {}
    # One row per configuration for the published page: the same results,
    # kept apart by card, driver and build instead of summed per game (#304).
    configs: dict[tuple, dict] = {}
    seen = unseen = 0
    for issue in issues(repo, token):
        rec = parse(issue.get("body") or "")
        if not rec:
            continue
        said = SAID_IN_WORDS.get(issue.get("number"))
        if said is not None:
            rec = dict(rec, result=said)
        elif not counts(rec, issue.get("body") or ""):
            unseen += 1
            continue
        # Every string is capped and type-checked here, not where it was
        # written: the writing side is this tool, the reading side is
        # whatever somebody typed into an issue.
        # Both lower case: "Feeder" in a hand-written block would open a
        # second bucket beside "feeder", split the counts, and put a route
        # name the dropdown does not have into somebody's advice.
        exe = text(rec.get("exe"), 120).lower()
        route = text(rec.get("route"), 40).lower()
        if not exe or not route or len(games) >= MAX_GAMES and exe not in games:
            continue
        seen += 1
        g = games.setdefault(exe, {"name": "", "routes": {}, "drivers": {},
                                   "measured": {}})
        if not g["name"]:
            g["name"] = text(rec.get("game"), 80)
        for key, bucket in (("route", "routes"), ("driver", "drivers")):
            value = route if key == "route" else text(rec.get("driver"), 40)
            if not value:
                continue
            row = g[bucket].setdefault(value, {"worked": 0, "failed": 0})
            row[rec["result"]] += 1
        # Only results that say what the game ships (2.0.6 on) have a
        # class: guessing it for the older ones would count DLSS games and
        # games without as one kind, which is the comparison this table
        # exists to avoid.
        api = text(rec.get("api"), 12).upper()
        up = text(rec.get("up"), 8).lower()
        if api in APIS and up in UPS:
            bump(by_class, f"{api}/{up}", route, rec["result"])
        drv = text(rec.get("driver"), 20)
        if DRIVER.match(drv):
            bump(by_driver, drv, route, rec["result"])
        key = (exe, route, text(rec.get("build"), 60), text(rec.get("api"), 12).upper(),
               text(rec.get("sm"), 12).lower(), text(rec.get("gpu"), 40),
               text(rec.get("driver"), 40), text(rec.get("tool"), 20))
        row = configs.setdefault(key, {"worked": 0, "failed": 0, "last": ""})
        row[rec["result"]] += 1
        # The day only, from GitHub's own clock: when this configuration was
        # last reported, not who reported it or which issue it was.
        row["last"] = max(row["last"], text(issue.get("created_at"), 10))
        # What it cost, kept per route and only where it worked: the
        # settings of a session that failed are the settings of a failure.
        # The route is the stripped one, or a record with a trailing space
        # files its cost under a route name the tool never asks about.
        res = number(rec.get("res"), 1, 100)
        if rec["result"] == "worked" and res is not None:
            seen_ms.setdefault(exe, {}).setdefault(route, []).append(
                (res, number(rec.get("ms"), 0, 10_000),
                 number(rec.get("fps"), 0, 10_000)))

    for exe, routes in seen_ms.items():
        for route, samples in routes.items():
            if not samples:
                continue
            row = {"n": len(samples),
                   "res": int(round(median([s[0] for s in samples])))}
            for i, key in ((1, "ms"), (2, "fps")):
                vals = [s[i] for s in samples if s[i] is not None]
                if vals:
                    row[key] = round(median(vals), 2)
            games[exe].setdefault("measured", {})[route] = row

    for g in games.values():
        if not g.get("measured"):
            g.pop("measured", None)   # a game nobody measured says nothing

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reports": seen,
        "games": dict(sorted(games.items())),
        "by_class": dict(sorted(by_class.items())),
        "by_driver": dict(sorted(by_driver.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                   encoding="utf8")
    page_dir = os.environ.get("PAGE_DIR")
    if page_dir:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import compat_page
        rows = [dict(zip(compat_page.KEYS, k), **v) for k, v in configs.items()]
        out = compat_page.write(payload, rows, Path(page_dir))
        print(f"{len(rows)} configurations -> {out}")
    print(f"{seen} results across {len(games)} games -> {OUT}"
          f" ({unseen} left out: the tool could not see their outcome)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
