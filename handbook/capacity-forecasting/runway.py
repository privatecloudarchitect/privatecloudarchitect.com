#!/usr/bin/env python3
"""runway.py - the estate capacity runway, rolled up the way the sheet teaches.

Reads time remaining in days, commitment-adjusted, per resource axis, per
cluster, then rolls up pessimistically: a cluster's runway is its first axis
to run out, and the estate's runway is its first cluster. The number is always
reported with its cluster and axis attached.

Optionally gates itself on ruler parity first (--parity expectations.json):
a projection measured against a drifted allocation policy looks precise and
reads wrong, so the gate refuses the runway when a declared expectation is
missing from a policy's settings read.

Usage:  python3 runway.py [--parity expectations.json] [--parity-warn]
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 healthy · 1 warning · 2 critical · 3 parity gate refused
"""

import json
import sys

from opslib import bearer, ops

AXES = {
    "mem":  "OnlineCapacityAnalytics|mem|alloc|timeRemainingWithCommit",
    "cpu":  "OnlineCapacityAnalytics|cpu|alloc|timeRemainingWithCommit",
    "disk": "OnlineCapacityAnalytics|diskspace|alloc|timeRemainingWithCommit",
}
CAP_DAYS = 366     # the platform caps Time Remaining near one year
CRIT, WARN = 30, 90


def days(v):
    if v is None:
        return "-"
    return "> 1yr" if v >= CAP_DAYS else f"{v:.0f}d"


def parity_gate(tok, path, warn_only):
    """Refuse the runway if any declared expectation is absent from its policy's
    settings read. Expectations: {"<policy name>": ["<substring>", ...]} - declare
    the strings that encode your allocation ratios, and drift becomes visible."""
    expectations = {k: v for k, v in json.loads(open(path).read()).items()
                    if not k.startswith("comment")}
    st, body = ops("GET", "/api/policies", tok,
                   params={"pageSize": 500, "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list policies -> HTTP {st}: {body}")
    by_name = {p["name"]: p["id"] for p in body.get("policySummaries", [])}
    failures = []
    for pname, needles in expectations.items():
        pid = by_name.get(pname)
        if pid is None:
            failures.append(f"policy not found: {pname}")
            continue
        st, settings = ops("GET", f"/api/policies/{pid}/settings", tok, params={
            "type": "CAPACITY_ALLOCATION_MODEL", "resourceKind": "ClusterComputeResource",
            "adapterKind": "VMWARE", "includeInherited": "true", "_no_links": "true"})
        if st != 200:
            failures.append(f"settings read failed for {pname}: HTTP {st}")
            continue
        blob = json.dumps(settings)
        for needle in needles:
            if needle not in blob:
                failures.append(f"{pname}: expected setting not present: {needle}")
    if failures:
        print("PARITY GATE " + ("WARNINGS" if warn_only else "REFUSED") + ":")
        for f in failures:
            print(f"  - {f}")
        if not warn_only:
            print("a drifted ruler looks precise and reads wrong; fix the policy "
                  "or the expectation before trusting any projection.")
            sys.exit(3)
    else:
        print(f"parity gate: {len(expectations)} policy(ies) match their declared expectations\n")


def main():
    argv = sys.argv[1:]
    parity_file = argv[argv.index("--parity") + 1] if "--parity" in argv else None
    tok = bearer()
    if parity_file:
        parity_gate(tok, parity_file, "--parity-warn" in argv)

    st, body = ops("GET", "/api/resources", tok, params={
        "resourceKind": "ClusterComputeResource", "adapterKind": "VMWARE",
        "pageSize": 500, "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list clusters -> HTTP {st}: {body}")
    clusters = [(r["identifier"], r["resourceKey"]["name"])
                for r in body.get("resourceList", [])]
    if not clusters:
        sys.exit("no clusters visible to this token; nothing to project")

    print(f"ESTATE CAPACITY RUNWAY - {len(clusters)} cluster(s), "
          f"allocation model, commitment-adjusted\n")
    print(f"  {'cluster':24}{'mem':>8}{'cpu':>8}{'disk':>8}{'runway':>9}")
    print("  " + "-" * 57)
    worst = None
    exit_code = 0
    for rid, name in sorted(clusters, key=lambda c: c[1]):
        st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                       body={"resourceId": [rid], "statKey": list(AXES.values())},
                       params={"_no_links": "true"})
        vals = {}
        for v in (body or {}).get("values", []):
            for s in v.get("stat-list", {}).get("stat", []):
                key = s.get("statKey", {}).get("key")
                data = s.get("data") or []
                if key and data:
                    vals[key] = data[-1]
        axis_days = {ax: vals.get(k) for ax, k in AXES.items()}
        present = {ax: d for ax, d in axis_days.items() if d is not None}
        binding = min(present, key=present.get) if present else None
        runway = present[binding] if binding else None
        mark = ""
        if runway is not None:
            if runway < CRIT:
                mark, exit_code = "  CRITICAL", max(exit_code, 2)
            elif runway < WARN:
                mark, exit_code = "  warning", max(exit_code, 1)
            if worst is None or runway < worst[0]:
                worst = (runway, name, binding)
        print(f"  {name:24}{days(axis_days['mem']):>8}{days(axis_days['cpu']):>8}"
              f"{days(axis_days['disk']):>8}{days(runway):>9}{mark}")
    print("  " + "-" * 57)
    if worst:
        wd, wn, wax = worst
        verdict = "CRITICAL" if wd < CRIT else ("warning" if wd < WARN else "healthy")
        print(f"\n  ESTATE RUNWAY: {days(wd)}  ({verdict}) - bound by {wn} on {wax}.")
        print("  First axis, first cluster: the estate can place projected demand this"
              " long before its\n  tightest cluster runs out, honoring resident commitments.")
    else:
        print("\n  no runway data yet (capacity analytics still computing for these clusters)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
