r"""Open every session with where the loop stands, not with the last report.

The round that starts from whatever arrived overnight fixes whatever
arrived overnight. The measurement - which class of answer the tool gives
most often, and whether the guard rails are alive - is what turns a pile of
reports into a backlog with an order. It is worth nothing if it is only run
when somebody remembers to run it, so it runs here.

Beside it, who is still waiting for an answer (`issue_round.py`). The close
rule and "everybody gets an answer" lived only in the notes, so their only
engine was somebody remembering them, and on 2026-09-18 that came to 34
reports never answered at all. Printing it here gives the rule an engine.

Offline and bounded: no network at session start. Both the corpus freshness
check (`state.py --online`) and the tracker itself (`issue_round.py
--online`) belong at the start of an issue round, where the triage skill
asks for them; here the cached picture is printed, and it says its own age.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent


def _run(name: str, budget: int) -> str:
    """What one of the measurements prints, or "" if it cannot run."""
    script = SRC / "_tools" / name
    if not script.is_file():
        return ""
    try:
        r = subprocess.run([sys.executable, str(script)], cwd=str(SRC),
                           capture_output=True, text=True, timeout=budget)
    except Exception:
        return ""
    return (r.stdout or "").strip()


def main() -> int:
    loop = _run("state.py", 85)       # 85 + 20 stays under the hook's own 120 s
    waiting = _run("issue_round.py", 20)
    if not loop and not waiting:
        return 0
    parts = []
    if loop:
        parts.append(
            "Where this project's improvement loop stands, measured from "
            "disk at session start. The top class is the backlog: a shape "
            "to fix, not a report to answer.\n\n" + loop[-4000:])
    if waiting:
        parts.append(
            "Who is still waiting for an answer, by the owner's own rules. "
            "Anything under NEVER ANSWERED or OURS TO ANSWER is a person "
            "waiting; CLOSEABLE is the three-day rule. Run the round rather "
            "than reporting these numbers back as news.\n\n" + waiting[-3000:])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        },
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
