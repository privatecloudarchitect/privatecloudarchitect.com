#!/usr/bin/env python3
"""converge.py - assert desired-state.json onto a VCF Operations instance.

The three behaviors the ops-estate sheet teaches, runnable:
  adopt-or-create by NAME   an object whose name is live is adopted (an
                            id-preserving PUT syncs formula and description
                            onto it); an absent name is created; ids are
                            output records, never inputs.
  level-triggered           run it again and a converged estate no-ops; a
                            drifted one repairs. Same command either way.
  no undeclared writes      only the names in desired-state.json are touched.

Usage:  python3 converge.py [--dry-run] [--state FILE]
        --state FILE converges a declaration other than desired-state.json, such as the one export.py writes
        from what you already built. It only creates and updates; nothing here deletes, and teardown.py is
        deliberately bound to the demonstration declaration so it can never be pointed at your own content.
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 on success; 1 on any failed write.
"""

import html
import json
import pathlib
import sys

from opslib import bearer, ops

DRY = "--dry-run" in sys.argv
HERE = pathlib.Path(__file__).resolve().parent
STATE = (pathlib.Path(sys.argv[sys.argv.index("--state") + 1]) if "--state" in sys.argv
         else HERE / "desired-state.json")


def live_supermetrics(tok):
    """{name: entry} for every live super metric (one page covers most estates)."""
    st, body = ops("GET", "/api/supermetrics", tok, params={"pageSize": 2000})
    if st != 200:
        sys.exit(f"FATAL: list supermetrics -> HTTP {st}: {body}")
    return {s["name"]: s for s in body.get("superMetrics", [])}


def plan(want, have):
    """What converging one declared object takes: "create", "unchanged" or "update".

    `have` is the live object found by NAME, or None. The declaration carries no id: when an update needs
    one it is read from the live object, so a repair keeps the id every reference already points at.
    The instance returns > and < as &gt; and &lt; in both fields, so the comparison is on the decoded text;
    compared raw, every formula with a comparison operator would read as drifted on every run."""
    if have is None:
        return "create"
    live = (html.unescape(have.get("formula") or ""), html.unescape(have.get("description") or ""))
    if live == (want["formula"], want["description"]):
        return "unchanged"
    return "update"


def main():
    state = json.loads(STATE.read_text())
    tok = bearer()
    live = live_supermetrics(tok)
    created = updated = unchanged = failed = 0

    for want in state["supermetrics"]:
        name = want["name"]
        have = live.get(name)
        action = plan(want, have)
        if action == "create":
            if DRY:
                print(f"  would create  {name}")
                created += 1
                continue
            st, body = ops("POST", "/api/supermetrics", tok, body={
                "name": name, "formula": want["formula"],
                "description": want["description"]})
            if st in (200, 201):
                print(f"  created       {name}")
                created += 1
            else:
                print(f"  FAILED create {name} -> HTTP {st}: {body}")
                failed += 1
            continue

        if action == "unchanged":
            print(f"  unchanged     {name}")
            unchanged += 1
            continue
        if DRY:
            print(f"  would update  {name}")
            updated += 1
            continue
        sm_id = have["id"].replace("SuperMetric-", "")
        st, body = ops("PUT", "/api/supermetrics", tok, body={
            "id": sm_id, "name": name, "formula": want["formula"],
            "description": want["description"]})
        if st in (200, 201):
            print(f"  updated       {name}  (id preserved: {sm_id[:8]}...)")
            updated += 1
        else:
            print(f"  FAILED update {name} -> HTTP {st}: {body}")
            failed += 1

    mode = "dry-run" if DRY else "converge"
    print(f"\n{mode}: {created} created, {updated} updated, {unchanged} unchanged"
          + (f", {failed} FAILED" if failed else ""))
    if not DRY and failed == 0 and (created or updated):
        print("run it again: a converged estate reports every object unchanged.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
