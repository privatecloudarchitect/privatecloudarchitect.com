#!/usr/bin/env python3
"""cycle.py - prove the converge on your own instance in one command, and leave nothing behind.

Runs the whole cycle the ops-estate chapter teaches against desired-state.json's two demonstration super
metrics, each step the command you would type yourself:

  1. converge.py --dry-run     reads only; shows what would change
  2. converge.py               creates what is absent
  3. converge.py               a converged estate is a no-op
  4. edit one formula, then converge.py
                               drift is repaired in place, and the object keeps its id
  5. delete the other object outside the converge, then converge.py
                               it is created again, and it comes back with a NEW id: the failure a rebuild by
                               teardown causes, shown on an object this script made
  6. teardown.py               deletes only the declared names, with a read-back
  7. export.py, then converge.py --state <exported> --dry-run
                               read-only: what you already built, exported and dry-run, is adopted by name
                               and reported unchanged

The drift edit is made on a temporary copy of this folder, so desired-state.json is never changed. Between
steps the script reads the super metric list itself, so "id preserved" is checked against the estate rather
than taken from converge.py's own message, and after the teardown it reads once more for residue.

Writes to your estate: the two demonstration super metrics, which no policy enables, so they compute nothing
and page nobody. If any step fails, the teardown still runs. It refuses to start if either name already
exists, because the demonstration would then adopt an object it did not create.

Usage:  python3 cycle.py
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...); OUT_DIR for the record (default: this folder)
Writes: converge-run.json, each step's command and output, plus the checks. The adoption step keeps only its
        summary line, so the record does not list your super metrics a second time.
Exit:   0 when every behavior held; 1 otherwise.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

from opslib import bearer, ops

# The cycle takes no arguments; refuse any rather than run the whole cycle on a stray flag such as --help.
if sys.argv[1:]:
    sys.exit(f"unknown argument(s) {sys.argv[1:]}: cycle.py takes none (see the docstring)")

HERE = pathlib.Path(__file__).resolve().parent
FILES = ("converge.py", "teardown.py", "export.py", "opslib.py", "desired-state.json")


def declared_ids(names):
    """{name: id} for the declared names that are live now, read directly rather than from a script's output."""
    st, body = ops("GET", "/api/supermetrics", bearer(), params={"pageSize": 2000})
    if st != 200:
        sys.exit(f"FATAL: list supermetrics -> HTTP {st}: {body}")
    return {s["name"]: s["id"] for s in body.get("superMetrics", []) if s["name"] in names}


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="ops-estate-cycle-"))
    for f in FILES:
        shutil.copy2(HERE / f, work / f)
    state_file = work / "desired-state.json"
    names = [s["name"] for s in json.loads(state_file.read_text())["supermetrics"]]

    st, ver = ops("GET", "/api/versions/current", bearer())
    record = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "build": ver.get("releaseName") if st == 200 and isinstance(ver, dict) else None,
              "steps": []}

    present = declared_ids(names)
    if present:
        sys.exit(f"refusing to start: {sorted(present)} already exist. Run teardown.py first, so the cycle only "
                 f"adopts objects it created.")

    def step(label, args, summary_only=False):
        r = subprocess.run([sys.executable] + args, cwd=work, capture_output=True, text=True, timeout=600)
        out = (r.stdout + r.stderr).rstrip("\n").split("\n")
        if summary_only:
            out = [ln for ln in out if ln.startswith(("dry-run:", "converge:", "FATAL", "Traceback"))] or out[-3:]
        record["steps"].append({"label": label, "command": "python3 " + " ".join(args), "exit": r.returncode,
                                "output": out})
        print(f"$ python3 {' '.join(args)}")
        print("\n".join(out) + "\n")
        if r.returncode != 0:
            raise RuntimeError(f"{label}: exit {r.returncode}")

    created = False
    ok = False
    try:
        step("dry run: reads only", ["converge.py", "--dry-run"])
        created = True
        step("first run: creates what is absent", ["converge.py"])
        after_create = declared_ids(names)
        step("second run: a converged estate is a no-op", ["converge.py"])

        state = json.loads(state_file.read_text())
        target = state["supermetrics"][0]
        before = target["formula"]
        target["formula"] = before.replace("/ 1048576)", "/ 1024 / 1024)")
        if target["formula"] == before:
            raise RuntimeError("the drift edit did not change the formula")
        state_file.write_text(json.dumps(state, indent=2) + "\n")
        record["drift"] = {"name": target["name"], "from": before, "to": target["formula"]}
        print(f"# edited the formula of {target['name']} in a temporary copy of desired-state.json\n")

        step("after editing one formula: drift repaired in place", ["converge.py"])
        after_drift = declared_ids(names)
        record["idPreservedAcrossDriftRepair"] = bool(after_drift) and after_create == after_drift

        other = names[1]
        st, body = ops("DELETE", f"/api/supermetrics/{after_drift[other]}", bearer())
        if st not in (200, 204):
            raise RuntimeError(f"delete outside the converge: HTTP {st}")
        print(f"# deleted {other} directly, outside the converge, the way a rebuild by teardown would\n")
        step("after deleting one object outside the converge: created again, with a new id", ["converge.py"])
        after_recreate = declared_ids(names)
        record["recreate"] = {"name": other,
                              "idChanged": bool(after_recreate.get(other)) and after_recreate[other] != after_drift[other]}
        step("teardown: deletes only the declared names", ["teardown.py"])
        created = False

        exp = subprocess.run([sys.executable, "export.py"], cwd=work, capture_output=True, text=True, timeout=600)
        if exp.returncode != 0:
            raise RuntimeError(f"export: exit {exp.returncode}: {exp.stderr.strip()[-200:]}")
        (work / "mine.json").write_text(exp.stdout, encoding="utf-8")
        exported = len(json.loads(exp.stdout)["supermetrics"])
        print(f"$ python3 export.py > mine.json\n{exp.stderr.strip()}\n")
        step("adoption: what you already built, exported and dry-run", ["converge.py", "--state", "mine.json", "--dry-run"],
             summary_only=True)
        record["adoption"] = {"exported": exported, **{k: int(v) for v, k in
                              re.findall(r"(\d+) (created|updated|unchanged)", record["steps"][-1]["output"][-1])}}
        ok = True
    except RuntimeError as e:
        record["stoppedAt"] = str(e)
        print(f"stopped: {e}")
    finally:
        if created:
            subprocess.run([sys.executable, "teardown.py"], cwd=work, timeout=600)
        shutil.rmtree(work, ignore_errors=True)

    record["residueAfterTeardown"] = len(declared_ids(names))
    text = json.dumps(record, indent=1, ensure_ascii=False)
    for var in ("OPS_HOST", "OPS_BROKER_HOST", "OPS_API_TOKEN"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    out_dir = pathlib.Path(os.environ.get("OUT_DIR", HERE))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "converge-run.json").write_text(text + "\n", encoding="utf-8")

    adoption = record.get("adoption") or {}
    held = (ok and record.get("idPreservedAcrossDriftRepair") and (record.get("recreate") or {}).get("idChanged")
            and record["residueAfterTeardown"] == 0 and adoption.get("unchanged") == adoption.get("exported"))
    print(f"id preserved across the drift repair: {record.get('idPreservedAcrossDriftRepair')}; "
          f"id changed when recreated: {(record.get('recreate') or {}).get('idChanged')}; "
          f"objects left after teardown: {record['residueAfterTeardown']}; "
          f"your own super metrics adopted unchanged: {adoption.get('unchanged')} of {adoption.get('exported')}")
    print("cycle: every behavior held" if held else "cycle: a behavior did not hold; read the steps above")
    print("wrote converge-run.json")
    return 0 if held else 1


if __name__ == "__main__":
    sys.exit(main())
