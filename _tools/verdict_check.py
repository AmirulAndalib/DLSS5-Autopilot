r"""Every real report, through the current diagnosis, against last time.

The fixes in this project keep breaking each other, and they do it in one
place above all others: `diagnose.py` is 236 if/elif branches and 62
verdicts over ONE input - the logs somebody sent. A rule put in front of
the others changes what all of them see, and nothing says so. That is how
`ours(written)` made `ambiguous()` unreachable, how the `cost:` rule
answered "neural rendering did not start" to a working install, and how a
report can get a verdict nobody meant to change.

So: keep every report anybody ever sent, replay all of them on every
change, and print the ones whose answer moved.

    python _tools\verdict_check.py            compare against the baseline
    python _tools\verdict_check.py --save     record the answers as they are
    python _tools\verdict_check.py --list     print them, change nothing
    python _tools\verdict_check.py --only 175 one report, in full

A changed verdict is not a failure - most changes here are meant. It is a
question: did you mean to change THIS one too? Answer it, then --save.

The corpus is `_tools\reports\<issue>.txt`: the issue bodies as posted, with
the tool's own autopilot.log block dropped and Windows account names
replaced by <user>. The baseline beside it is committed, so the answer is
the same on any machine - the driver comes from each report's own header
rather than from the card in this PC, and the standalone add-on's log is
read from the report instead of from this machine's AppData.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import replay_report                       # noqa: E402
from core import diagnose                  # noqa: E402

REPORTS = HERE / "reports"
BASELINE = HERE / "verdict_baseline.json"

API_RE = re.compile(r"(DX9|DX10|DX11|DX12|Vulkan|OpenGL)")


# The four verdicts diagnose.analyse() can only reach through the
# `complete is False` branch, which returns before anything else is read.
# A report carrying one of them proves the install record said "unfinished";
# a report carrying any OTHER verdict proves it did not.
UNFINISHED = (
    "The install never finished - install again.",
    "The install stopped for a reason of its own - see below.",
    "The drive was full - free up space and install again.",
    "The uninstall left files behind - close the game and uninstall again.",
)


def _finished(text: str) -> dict:
    """Whether the install record in that folder said the install finished.

    Not in the report as a field, and it decides everything: the unfinished
    branch returns before any log is read. Two things in the report settle
    it - the verdict the machine printed (it proves which side of that
    branch it came out of), and, when there is none, whether the report
    carries a traceback out of the installer, which is what a install that
    stopped part way leaves behind (#97, #103).
    """
    said = printed_verdict(text)
    if said:
        return {"complete": said not in UNFINISHED}
    crashed = re.search(r"\*\*Last error\*\*(.*?)```", text, re.S) is not None \
        and "installer.py" in text
    return {"complete": not crashed}


def _answer(path: Path) -> dict:
    """What the diagnosis says about one saved report, on any machine."""
    # Git may hand these back with CRLF on another checkout, and a log line
    # that ends in \r is not the same string to a rule that matches the end
    # of one. The baseline has to mean the same thing everywhere.
    text = path.read_text(encoding="utf8", errors="replace").replace("\r\n", "\n")
    logs = replay_report._blocks(text)
    head = replay_report._header(text)
    route = head.get("route", "feeder")
    exe = head.get("exe", "Game.exe")
    api, bitness = "DX12", 64
    if "arch/api" in head:
        m = API_RE.search(head["arch/api"])
        if m:
            api = m.group(1)
        if "32-bit" in head["arch/api"]:
            bitness = 32
    # The folder as the report describes it, not as an install that went
    # perfectly would leave it: which files were on disk, and whether there
    # was an install record at all. Replaying every report against a
    # complete folder made the biggest class in the corpus - "nothing we
    # wrote ever loaded" - unreproducible, because the reason was on the
    # disk and the replay put it back (#43, #194).
    state = replay_report.folder_state(text)
    d = replay_report.build(route, api, exe, logs, bitness, state=state,
                            extra_manifest=_finished(text))
    try:
        # What the diagnosis asks the MACHINE for - the standalone log's
        # path, the Vulkan layer registry, the driver version - comes out of
        # the report instead, so the answer is the same on any PC. The
        # patching lives in replay_report so a report replayed by hand there
        # gets the same verdict this measures (it did not: #212).
        with replay_report.machine(text, d):
            rep = diagnose.analyse(d, replay_report.last_error(text))
        return {
            "route": rep.route or "",
            "ran": bool(rep.ran),
            "never_ran": bool(getattr(rep, "never_ran", False)),
            "verdict": rep.verdict or "",
            "findings": [f"{f.level}: {f.title}" for f in rep.findings],
        }
    finally:
        shutil.rmtree(d, ignore_errors=True)


def printed_verdict(text: str) -> str:
    """The verdict the tool printed on the reporter's own machine.

    Most reports carry it: the report template puts the diagnosis in. It is
    the only ground truth there is for whether a replay reproduces the
    machine it came from - if the replay says something else, the fault may
    be in the rule OR in the replay, and until 1.8.2 nothing compared them.
    """
    m = re.search(r"^\*\*Diagnosis\*\*:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def reproduction(new: dict) -> tuple[int, int, list[str]]:
    """How many reports the replay answers the way the machine did."""
    same, total, off = 0, 0, []
    for p in sorted(REPORTS.glob("*.txt")):
        n = p.stem.lstrip("0") or p.stem
        said = printed_verdict(p.read_text(encoding="utf8", errors="replace")
                               .replace("\r\n", "\n"))
        if not said or n not in new:
            continue
        total += 1
        got = str(new[n].get("verdict", ""))
        if got == said:
            same += 1
        else:
            off.append(f"  #{n}\n     machine: {said}\n     replay:  {got}")
    return same, total, off


def answers(only: str = "") -> dict:
    out = {}
    for p in sorted(REPORTS.glob("*.txt")):
        n = p.stem.lstrip("0") or p.stem
        if only and n != only.lstrip("#"):
            continue
        try:
            out[n] = _answer(p)
        except Exception as e:                     # a crash IS the finding
            out[n] = {"error": f"{type(e).__name__}: {e}"}
    return out


def _diff(old: dict, new: dict) -> list[str]:
    """Every report whose answer moved, said in one place."""
    lines: list[str] = []
    for n in sorted(set(old) | set(new), key=lambda x: int(x) if x.isdigit() else 0):
        a, b = old.get(n), new.get(n)
        if a == b:
            continue
        if a is None:
            lines.append(f"  NEW  #{n}: {b.get('verdict', b)}")
            continue
        if b is None:
            lines.append(f"  GONE #{n}")
            continue
        lines.append(f"  #{n}")
        if a.get("error") or b.get("error"):
            lines.append(f"     error: {a.get('error', '-')} -> {b.get('error', '-')}")
        if a.get("verdict") != b.get("verdict"):
            lines.append(f"     verdict was: {a.get('verdict')}")
            lines.append(f"             now: {b.get('verdict')}")
        for k in ("ran", "never_ran", "route"):
            if a.get(k) != b.get(k):
                lines.append(f"     {k}: {a.get(k)} -> {b.get(k)}")
        gone = [f for f in a.get("findings", []) if f not in b.get("findings", [])]
        came = [f for f in b.get("findings", []) if f not in a.get("findings", [])]
        for f in gone:
            lines.append(f"     - {f}")
        for f in came:
            lines.append(f"     + {f}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--reproduce", action="store_true",
                    help="compare the replay against the verdict each report "
                         "says the tool printed on the reporter's machine")
    a = ap.parse_args()

    if not REPORTS.is_dir() or not any(REPORTS.glob("*.txt")):
        print(f"no reports in {REPORTS}")
        return 2
    new = answers(a.only)

    if a.reproduce:
        same, total, off = reproduction(new)
        print("=" * 78)
        print(f"REPLAY vs THE MACHINE: {same} of {total} report(s) that carry "
              f"a printed verdict come back the same")
        print("=" * 78)
        for ln in off:
            print(ln)
        return 0

    if a.list or a.only:
        for n, r in new.items():
            print("=" * 78)
            print(f"#{n}  route={r.get('route')}  ran={r.get('ran')}")
            print(f"  VERDICT: {r.get('verdict', r.get('error'))}")
            for f in r.get("findings", []):
                print(f"    {f}")
        return 0

    if a.save:
        BASELINE.write_text(json.dumps(new, indent=1, sort_keys=True) + "\n",
                            encoding="utf8")
        print(f"recorded {len(new)} answers in {BASELINE.name}")
        return 0

    if not BASELINE.is_file():
        print(f"no baseline yet - run --save once: {BASELINE}")
        return 2
    old = json.loads(BASELINE.read_text(encoding="utf8"))
    lines = _diff(old, new)
    crashed = [n for n, r in new.items() if r.get("error")]
    print("=" * 78)
    print(f"{len(new)} REAL REPORTS THROUGH THE CURRENT DIAGNOSIS")
    print("=" * 78)
    if crashed:
        print(f"  !! the diagnosis raised on: {', '.join('#' + n for n in crashed)}")
    if not lines:
        print("  nothing moved: every report still gets the answer it got.")
        return 1 if crashed else 0
    print(f"  {len([x for x in lines if x.startswith('  #')])} report(s) answer "
          f"differently than they did:")
    print()
    for ln in lines:
        print(ln)
    print()
    print("If every one of those was meant, record them: "
          "python _tools\\verdict_check.py --save")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
