#!/usr/bin/env python3
"""teardown.py - remove ONLY the objects desired-state.json declares.

Teardown is a separate, deliberate, scoped tool, exactly as the sheet says:
it never deletes by pattern or prefix, only by the declared names, and it
verifies each deletion with a read-back. Run converge.py afterward to prove
the cycle: the estate returns to created-from-empty.

Usage:  python3 teardown.py [--dry-run]
Exit:   0 on success (including nothing-to-delete); 1 on any failed delete.
"""

import json
import pathlib
import sys

from opslib import bearer, ops

DRY = "--dry-run" in sys.argv
HERE = pathlib.Path(__file__).resolve().parent


def main():
    state = json.loads((HERE / "desired-state.json").read_text())
    declared = [s["name"] for s in state["supermetrics"]]
    tok = bearer()
    st, body = ops("GET", "/api/supermetrics", tok, params={"pageSize": 2000})
    if st != 200:
        sys.exit(f"FATAL: list supermetrics -> HTTP {st}: {body}")
    live = {s["name"]: s["id"] for s in body.get("superMetrics", [])}

    deleted = absent = failed = 0
    for name in declared:
        full_id = live.get(name)
        if full_id is None:
            print(f"  absent        {name}")
            absent += 1
            continue
        if DRY:
            print(f"  would delete  {name}")
            deleted += 1
            continue
        st, body = ops("DELETE", f"/api/supermetrics/{full_id}", tok)
        if st in (200, 204):
            print(f"  deleted       {name}")
            deleted += 1
        else:
            print(f"  FAILED delete {name} -> HTTP {st}: {body}")
            failed += 1

    if not DRY and deleted:
        st, body = ops("GET", "/api/supermetrics", tok, params={"pageSize": 2000})
        left = [s["name"] for s in body.get("superMetrics", []) if s["name"] in declared]
        print("  read-back:    " + ("all declared names gone" if not left
                                    else f"STILL PRESENT: {left}"))
        if left:
            failed += 1

    mode = "dry-run" if DRY else "teardown"
    print(f"\n{mode}: {deleted} deleted, {absent} already absent"
          + (f", {failed} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
