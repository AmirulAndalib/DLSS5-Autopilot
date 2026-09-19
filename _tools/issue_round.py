r"""Who is still waiting for an answer, and what the close rule says today.

    python _tools\issue_round.py              the cached picture, offline
    python _tools\issue_round.py --online     ask the tracker, then cache
    python _tools\issue_round.py --json       machine-readable

The close rule ("a report the reporter has not answered for three days gets
closed") and the rule above it ("everybody gets an answer") were written
down in the notes and nowhere else. Nothing ran them, so their only engine
was somebody remembering, and on 2026-09-18 the count was 34 reports that
had never been answered at all and 31 sitting past the close rule. A rule
whose engine is memory is not a rule.

So this measures it instead, from dates GitHub itself records, and the
session-start hook prints it whether or not anybody asked:

    NEVER ANSWERED      nobody has written a word back to this person
    OURS TO ANSWER      they wrote last: a test we asked for, or a fix that
                        did not work, and it is waiting on us
    CLOSEABLE           we wrote last and it has been quiet >= CLOSE_DAYS

The three are counted the same way every day, so a good week and a bad one
look different. Nothing is posted and nothing is closed from here: it says
who is waiting, the round answers them (the `issue-triage` skill), and the
owner decides what gets posted.

The cache lives beside the tool's own, not in the repository: it is this
account's view of a public page.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import net  # noqa: E402

REPO = "Kizzuwatnaa/DLSS5-Autopilot"
OWNER = "Kizzuwatnaa"
CACHE = (Path(os.environ.get("LOCALAPPDATA", Path.home()))
         / "dlss5-autopilot" / "issue-round.json")

# The owner's rule, 2026-09-17: three days, not two.
CLOSE_DAYS = 3
# Past this, "waiting for an answer" is not the word for it any more.
LATE_DAYS = 2


def _token() -> str:
    """The git credential helper's token, or "" - it only raises the limit."""
    try:
        p = subprocess.run(["git", "credential", "fill"],
                           input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return ""
    for line in (p.stdout or "").splitlines():
        if line.startswith("password="):
            return line[9:].strip()
    return ""


def _get(path: str, token: str):
    req = urllib.request.Request("https://api.github.com/repos/" + REPO + path,
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "dlss5-issue-round"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60,
                                context=net.ssl_context()) as r:
        return json.load(r)


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gather() -> dict:
    """Every open report, with who spoke last and how long ago."""
    token = _token()
    now = datetime.now(timezone.utc)
    rows, page = [], 1
    while page <= 10:
        batch = _get("/issues?state=open&per_page=100&sort=updated&page=%d" % page,
                     token)
        if not batch:
            break
        rows.extend(batch)
        page += 1
    out = []
    for it in rows:
        if "pull_request" in it:            # a PR is not a report
            continue
        n = int(it["number"])
        comments = _get("/issues/%d/comments?per_page=100" % n, token) \
            if it.get("comments") else []
        ours = sum(1 for c in comments
                   if (c.get("user") or {}).get("login") == OWNER)
        last = comments[-1] if comments else None
        who = (last["user"]["login"] if last else it["user"]["login"])
        at = _when(last["created_at"] if last else it["created_at"])
        out.append({
            "number": n,
            "title": it.get("title") or "",
            "author": it["user"]["login"],
            "opened": it["created_at"][:10],
            "opened_days": (now - _when(it["created_at"])).days,
            "comments": len(comments),
            "we_replied": ours,
            "last_who": who,
            "last_is_us": who == OWNER,
            "silent_days": (now - at).days,
            "last_at": at.isoformat(),
        })
    return {"at": now.isoformat(), "open": len(out), "issues": out}


def _split(data: dict) -> dict:
    """The three questions, answered the same way every day."""
    never, ours, closeable, fresh = [], [], [], []
    now = datetime.now(timezone.utc)
    for r in data.get("issues") or []:
        # counted when it is read, not when it was fetched: the cache is read
        # for up to a day, and a wait that was 2 days then is 3 by the evening
        if r.get("last_at"):
            try:
                r["silent_days"] = (now - datetime.fromisoformat(r["last_at"])).days
            except (ValueError, TypeError):
                pass
        if not r["we_replied"]:
            (never if r["silent_days"] >= LATE_DAYS else fresh).append(r)
        elif not r["last_is_us"]:
            ours.append(r)
        elif r["silent_days"] >= CLOSE_DAYS:
            closeable.append(r)
    key = lambda r: (-r["silent_days"], r["number"])   # noqa: E731
    return {"never": sorted(never, key=key), "ours": sorted(ours, key=key),
            "closeable": sorted(closeable, key=key),
            "fresh": sorted(fresh, key=key)}


def _unposted_plan() -> str:
    """A written-out round that never reached the tracker.

    2026-09-18's real fault was not an unmeasured backlog: an 84-entry plan
    of replies and closes had been written the day before and was still
    sitting on the disk with an empty post log. Drafted is not answered, so
    a plan with nothing posted against it is said out loud here too.
    """
    desk = Path(__file__).resolve().parent.parent.parent
    plan, log = desk / "issue_plan.json", desk / "issue_post_log.txt"
    if not plan.is_file():
        return ""
    try:
        entries = json.loads(plan.read_text(encoding="utf8"))
        posted = log.read_text(encoding="utf8").strip() if log.is_file() else ""
    except Exception:
        return ""
    if posted or not entries:
        return ""
    day = datetime.fromtimestamp(plan.stat().st_mtime, timezone.utc)
    old = (datetime.now(timezone.utc) - day) >= timedelta(days=1)
    return ("issue_plan.json holds %d reply/close(s) and issue_post_log.txt is "
            "empty - written %s, nothing posted%s. Drafted is not answered: "
            "check it is still true, then run post_issue_plan.py --dry."
            % (len(entries), day.date().isoformat(),
               " (a day or more ago)" if old else ""))


def _line(rows: list, limit: int = 12) -> str:
    shown = " ".join("#%d" % r["number"] for r in rows[:limit])
    if len(rows) > limit:
        shown += " +%d more" % (len(rows) - limit)
    return shown


def report(data: dict) -> None:
    g = _split(data)
    age = ""
    try:
        hours = (datetime.now(timezone.utc) - _when(data["at"])).total_seconds() / 3600
        if hours >= 24:
            age = "  (%d day(s) old - run with --online)" % int(hours // 24)
    except Exception:
        pass
    print("=" * 78)
    print("WHO IS WAITING FOR AN ANSWER" + age)
    print("=" * 78)
    print()
    print("  %3d open report(s) on the tracker" % data.get("open", 0))
    print()
    rules = (
        ("NEVER ANSWERED", g["never"],
         "nobody has written back, and it is %d+ days old" % LATE_DAYS),
        ("OURS TO ANSWER", g["ours"],
         "they wrote last - a test we asked for, or a fix that did not work"),
        ("CLOSEABLE", g["closeable"],
         "we wrote last, quiet for %d+ days - reply-and-close" % CLOSE_DAYS),
    )
    for name, rows, why in rules:
        mark = "  " if not rows else ">>"
        print("%s %-16s %3d   %s" % (mark, name, len(rows), why))
        if rows:
            print("     %s" % _line(rows))
            oldest = rows[0]
            print("     oldest: #%d, waiting %d day(s)"
                  % (oldest["number"], oldest["silent_days"]))
        print()
    if g["fresh"]:
        print("  (%d just arrived, under %d days: %s)"
              % (len(g["fresh"]), LATE_DAYS, _line(g["fresh"], 8)))
        print()
    pending = _unposted_plan()
    if pending:
        print("  >> %s" % pending)
        print()
    if g["never"] or g["ours"] or g["closeable"]:
        print("  Run the round: the `issue-triage` skill. Drafts go in")
        print("  ISSUE-YORUMLARI-<version>.md; nothing is posted without the owner.")
    else:
        print("  Nobody is waiting.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--online", action="store_true",
                    help="ask the tracker instead of reading the cache")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    data = None
    if a.online:
        try:
            data = gather()
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(data), encoding="utf8")
        except Exception as exc:
            print("could not reach the tracker: %s" % exc, file=sys.stderr)
    if data is None:
        if not CACHE.is_file():
            print("no cached picture yet - run: python _tools\\issue_round.py --online")
            return 0
        try:
            data = json.loads(CACHE.read_text(encoding="utf8"))
        except Exception:
            print("the cached picture could not be read - run with --online")
            return 0

    if a.json:
        print(json.dumps({"at": data.get("at"), "open": data.get("open"),
                          **{k: [r["number"] for r in v]
                             for k, v in _split(data).items()}}, indent=1))
        return 0
    report(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
