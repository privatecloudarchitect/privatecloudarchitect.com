#!/usr/bin/env python3
"""record_dryrun.py: run the converge as a dry run and keep what it said, as a record you can archive and compare.

A converge is level-triggered, so its dry run is a report of the distance between these files and your estate,
and that distance is supposed to move. This runs `apply.py` in its default dry-run mode (it never passes
--execute), and writes `dryrun.json`: each step and each parity gate with its command, its exit code and the
lines that summarize it. Object listings are dropped, ids are masked, host names and file paths are replaced
by placeholders, and a dash is written as a colon (the handbook's typography, which renders these lines), so the record carries counts and outcomes, not your estate's names; it refuses to write a record
in which a host name survived. Diff this week's record against last week's: the day the pending list grows an
entry is the day something changed that nobody declared.

Run:  python3 record_dryrun.py [posture ...] [--against LAST_WEEK.json]   (environment as for apply.py; read-only)
Env:  OUT_DIR for the record (default: this folder)

With --against, it also compares the new record with an earlier one: steps that appeared or went, exit codes that
moved, and summary lines that changed. It exits 1 when the pending list (the steps with a non-zero exit) differs,
because that is the change nobody declared, and 0 when it is the same; summary lines that moved are printed either
way. Keep each week's dryrun.json under its date and pass last week's.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = re.compile(r"^> (step|verify): (?P<label>.+?)\s{2,}\((?P<cmd>.*)\)\s*$")
EXITED = re.compile(r"^x (?P<label>.+) exited (?P<rc>\d+)\s*$")
KEEP = re.compile(r"summary:|DRY-RUN|REFUSING|Re-run once|posted=|keep=\d|would|priority:|skipped:|hardware governance|"
                  r"VMs group:|derived from ancestry|✓|✅|❌|⚠|exists:|ADOPTED|nothing to check|SHADOWED|UNTIERED")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
SHORT_ID = re.compile(r"(?<=[ (=/])[0-9a-f]{8}(?=[ )\]:./]|$)")
# a host name, but not a file name: the last label is never a file extension
FQDN = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.(?!(?:yaml|yml|json|py|md|zip|xml|txt|html|csv)\b)[a-z]{2,}\b", re.I)
# a local file path, not an API path
PATH = re.compile(r"/(?:private|Users|home|tmp|var|opt|mnt|Volumes|root)(?:/[\w.@-]+)+")


def scrub(line: str) -> str:
    line = line.replace(" \u2014 ", ": ").replace("\u2014", ": ").replace("\u2013", "-")
    line = PATH.sub("<path>", line)                 # first: an id inside a path is part of the path
    line = UUID.sub("{{id}}", line)
    line = FQDN.sub("<host>", line)
    return SHORT_ID.sub("{{id}}", line).rstrip()


def compare(old: dict, new: dict) -> tuple[bool, list[str]]:
    """What moved between two dry-run records; True when the pending list (steps with a non-zero exit) differs."""
    before = {s["label"]: s for s in old.get("steps", [])}
    after = {s["label"]: s for s in new.get("steps", [])}
    pending = lambda r: sorted(s["label"] for s in r.get("steps", []) if s["exit"])  # noqa: E731
    lines = [f"compared with the record of {old.get('captured_utc', '?')}"]
    for label in sorted(set(after) - set(before)):
        lines.append(f"  new step: {label} (exit {after[label]['exit']})")
    for label in sorted(set(before) - set(after)):
        lines.append(f"  step gone: {label}")
    for label in [x for x in after if x in before]:
        a, b = before[label], after[label]
        if a["exit"] != b["exit"]:
            lines.append(f"  {label}: exit {a['exit']} -> {b['exit']}")
        gone = [x for x in a["summary"] if x not in b["summary"]]
        came = [x for x in b["summary"] if x not in a["summary"]]
        if gone or came:
            lines.append(f"  {label}: summary changed")
            lines += [f"    - {x}" for x in gone] + [f"    + {x}" for x in came]
    changed = pending(old) != pending(new)
    lines.append("  the pending list " + (f"changed: {pending(old)} -> {pending(new)}" if changed else "is the same"))
    return changed, lines


def main() -> int:
    args = sys.argv[1:]
    against = None
    if "--against" in args:
        i = args.index("--against")
        if i + 1 >= len(args):
            sys.exit("--against needs the earlier dryrun.json to compare with")
        against = args[i + 1]
        del args[i:i + 2]
    postures = [a for a in args if not a.startswith("-")]
    flags = [a for a in args if a.startswith("-")]
    if flags:
        sys.exit(f"record_dryrun.py takes posture names and --against only (it always runs the dry run); refused: {flags}")
    previous = None
    if against:
        with open(against, encoding="utf-8") as f:
            previous = json.load(f)
    env = dict(os.environ, PYTHONUNBUFFERED="1")      # keep apply.py's headers in order with its steps' output
    r = subprocess.run([sys.executable, "apply.py", *postures], cwd=HERE, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, timeout=3600)     # one stream, so a step's errors stay in it
    lines = r.stdout.splitlines()
    record = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "command": "python3 apply.py" + "".join(f" {p}" for p in postures), "exit": r.returncode,
              "steps": [], "verdict": None}
    current = None
    for ln in lines:
        m = HEADER.match(ln)
        if m:
            current = {"kind": m.group(1), "label": m.group(2), "command": scrub(m.group("cmd").strip()),
                       "exit": 0, "summary": []}
            record["steps"].append(current)
            continue
        m = EXITED.match(ln)
        if m:
            for s in record["steps"]:
                if s["label"] == m.group("label"):
                    s["exit"] = int(m.group("rc"))
            continue
        if ln.startswith(("OK WTPC apply", "! WTPC apply", "⚠ WTPC apply")):
            record["verdict"] = scrub(ln)
            continue
        stripped = ln.strip()
        if current and stripped and not stripped.startswith(("+", "~", "-")) and KEEP.search(stripped):
            current["summary"].append(scrub(stripped))
    if not record["steps"]:
        sys.exit("no step headers in apply.py's output; nothing recorded")
    text = json.dumps(record, indent=1, ensure_ascii=False)
    if FQDN.search(text.replace("<host>", "")):
        sys.exit("a host name survived the scrub; refusing to write the record")
    out = os.path.join(os.environ.get("OUT_DIR", HERE), "dryrun.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    pending = [s["label"] for s in record["steps"] if s["exit"]]
    print(f"recorded {len(record['steps'])} steps and gates; {len(pending)} non-zero: {pending}; verdict: {record['verdict']}")
    print(f"wrote {out}")
    if previous is None:
        return 0
    changed, lines = compare(previous, record)
    for line in lines:
        print(line)
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
