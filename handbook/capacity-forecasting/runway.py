#!/usr/bin/env python3
"""runway.py - the estate capacity runway, rolled up the way the sheet teaches.

Reads time remaining in days per resource axis per cluster, then rolls up pessimistically: a
cluster's runway is its first axis to run out, and the estate's runway is its first cluster. The
number is always reported with its cluster and axis attached.

Three things it does that a single-number read does not:

  THE GRID, NOT A KEY. Time remaining is not one metric. It is three axes by two capacity models
  (allocation and demand) by two flavours (plain, and commitment-adjusted), plus the platform's own
  per-cluster roll-up. The allocation model asks when configured capacity runs out and the demand
  model asks when observed demand does; on an overcommitted estate they can be a year apart, and
  reporting one of them as "the runway" hides which question was answered.

  THE CAP. The platform caps time remaining at one year. A cluster reading the cap is not "years
  from full", it is "past the horizon this metric measures", and every cluster at the cap reads
  identically. The metric screens; it does not rank. Runs print how many clusters are pinned there
  so a flat table is read as a saturated metric rather than a healthy fleet.

  THE RULER, CHECKED PROPERLY. A projection is measured against the governing policy's allocation
  model, so a drifted policy projects precisely and reads wrong. --parity compares PARSED ratios
  against declared ones, not substrings against serialized JSON: a substring test passes "cpu": 1
  against a ruler that has drifted to 15.0, and refuses a correct ruler written without the space
  the serializer happens to emit. It also reports each block's `inherited` flag, because a value
  the policy merely inherits from the default is not a value the policy sets, and verifying one is
  not verifying the other.

The severity thresholds come from the policy too, rather than from constants in this file: the
ruler carries its own critical and warning day counts, and a harness that verifies the ruler and
then grades against its own numbers has verified nothing that it then used.

Usage:  python3 runway.py [--parity expectations.json] [--parity-warn] [--model alloc|demand|both]
                          [--record runway.json]
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 healthy - 1 warning - 2 critical - 3 parity gate refused
"""

import json
import os
import sys
import time

from opslib import bearer, ops

AXES = ("cpu", "mem", "diskspace")
MODELS = ("alloc", "demand")
CAP_DAYS = 366          # the platform caps time remaining at one year; verified live
FALLBACK_CRIT, FALLBACK_WARN = 30, 90   # used only when the policy carries no thresholds
SETTINGS_BASE = {"resourceKind": "ClusterComputeResource", "adapterKind": "VMWARE",
                 "includeInherited": "true", "_no_links": "true"}


def key(axis, model, commit):
    return (f"OnlineCapacityAnalytics|{axis}|{model}|"
            + ("timeRemainingWithCommit" if commit else "timeRemaining"))


def days(v):
    if v is None:
        return "-"
    return "cap" if v >= CAP_DAYS else f"{v:.0f}d"


def settings(tok, pid, stype):
    """One settings block. `type` is REQUIRED (the endpoint 400s without it) and it selects which
    block comes back: CAPACITY_ALLOCATION_MODEL the overcommit ratios, CAPACITY_BUFFER the buffers,
    TIME_REMAINING the criticality thresholds. Two chapters reading 'the settings endpoint' and
    finding different things are both right; they passed different types."""
    st, body = ops("GET", f"/api/policies/{pid}/settings", tok, params=dict(SETTINGS_BASE, type=stype))
    return (body or {}) if st == 200 else None


def allocation_of(tok, pid):
    """(ratios, inherited) for a policy, or (None, None). Parsed, never string-matched."""
    body = settings(tok, pid, "CAPACITY_ALLOCATION_MODEL")
    if not body:
        return None, None
    rows = (body.get("capacitySettings", {}).get("capacity", {})
            .get("capacityAllocationSettings") or [])
    if not rows:
        return None, None
    return rows[0].get("capacityAllocation") or {}, rows[0].get("inherited")


def thresholds_of(tok, pid):
    """(critical_days, warning_days, inherited) from the policy's own TIME_REMAINING block."""
    body = settings(tok, pid, "TIME_REMAINING")
    if not body:
        return None, None, None
    rows = (body.get("capacitySettings", {}).get("criticalityThresholds", {})
            .get("timeRemainingSettings") or [])
    if not rows:
        return None, None, None
    cfg = rows[0].get("criticalityThresholdsConfig") or {}
    return cfg.get("critical"), cfg.get("warning"), rows[0].get("inherited")


def parity_gate(tok, path, warn_only):
    """Refuse the runway when a governing policy's PARSED allocation ratios differ from the
    declared ones. Expectations: {"<policy name>": {"cpu": 1.5, "memory": 1.0, "diskspace": 2.0}}.

    Comparing parsed numbers is the whole point. The earlier form of this gate matched declared
    substrings against json.dumps(settings), which passes "cpu": 1 against a ruler that reads 15.0
    and refuses "cpu":1.5 against a ruler that reads exactly 1.5, because the serializer puts a
    space after the colon. Both directions were reproduced before this was rewritten.
    """
    declared = {k: v for k, v in json.loads(open(path).read()).items()
                if not k.startswith("comment")}
    st, body = ops("GET", "/api/policies", tok, params={"pageSize": 500, "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list policies -> HTTP {st}: {body}")
    by_name = {p["name"]: p["id"] for p in body.get("policySummaries", [])}
    failures, notes = [], []
    for pname, want in declared.items():
        pid = by_name.get(pname)
        if pid is None:
            failures.append(f"policy not found: {pname}")
            continue
        got, inherited = allocation_of(tok, pid)
        if got is None:
            failures.append(f"{pname}: no allocation model in the policy's settings read")
            continue
        if inherited:
            notes.append(f"{pname}: the allocation model is INHERITED, so this policy does not set "
                         f"it; you are verifying the default showing through")
        for axis, expect in want.items():
            actual = got.get(axis)
            if actual is None:
                failures.append(f"{pname}: {axis} absent from the allocation model")
            elif float(actual) != float(expect):
                failures.append(f"{pname}: {axis} declared {expect}, ruler reads {actual}")
    for n in notes:
        print(f"  note: {n}")
    if failures:
        print("PARITY GATE " + ("WARNINGS" if warn_only else "REFUSED") + ":")
        for f in failures:
            print(f"  - {f}")
        if not warn_only:
            print("a drifted ruler looks precise and reads wrong; fix the policy or the "
                  "expectation before trusting any projection.")
            sys.exit(3)
    else:
        print(f"parity gate: {len(declared)} policy(ies) match their declared ratios exactly\n")


def reservation_census(tok):
    """How many machines carry a reservation. Without one, the commitment-adjusted flavour has
    nothing to honour and reads identically to the plain one, which is a fact about the estate and
    not about the metric. One read settles it, and it is worth printing beside a flat pair."""
    st, body = ops("GET", "/api/resources", tok,
                   params={"resourceKind": "VirtualMachine", "pageSize": 2000, "_no_links": "true"})
    if st != 200:
        return None
    ids = [r["identifier"] for r in (body or {}).get("resourceList") or []]
    if not ids:
        return None
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   {"resourceId": ids, "statKey": ["config|memoryAllocation|reservation",
                                                   "config|cpuAllocation|reservation"]})
    if st != 200:
        return None
    n = 0
    for v in (body or {}).get("values") or []:
        for s in v.get("stat-list", {}).get("stat", []):
            data = s.get("data") or []
            if data and data[-1]:
                n += 1
                break
    return {"machines": len(ids), "withAReservation": n}


def main():
    argv = sys.argv[1:]
    parity_file = argv[argv.index("--parity") + 1] if "--parity" in argv else None
    model_arg = argv[argv.index("--model") + 1] if "--model" in argv else "both"
    record_path = argv[argv.index("--record") + 1] if "--record" in argv else None
    models = MODELS if model_arg == "both" else (model_arg,)
    tok = bearer()
    if parity_file:
        parity_gate(tok, parity_file, "--parity-warn" in argv)

    st, body = ops("GET", "/api/resources", tok, params={
        "resourceKind": "ClusterComputeResource", "adapterKind": "VMWARE",
        "pageSize": 500, "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list clusters -> HTTP {st}: {body}")
    clusters = [(r["identifier"], r["resourceKey"]["name"])
                for r in body.get("resourceList", []) if r.get("identifier")]
    if not clusters:
        sys.exit("no clusters visible to this token; nothing to project")

    crit, warn = FALLBACK_CRIT, FALLBACK_WARN
    source = "this script's fallback constants"
    st, body = ops("GET", "/api/policies", tok, params={"pageSize": 500, "_no_links": "true"})
    if st == 200:
        for p in (body or {}).get("policySummaries", []):
            c, w, inh = thresholds_of(tok, p["id"])
            if c is not None and w is not None:
                crit, warn = c, w
                source = f"the policy's own TIME_REMAINING block{' (inherited)' if inh else ''}"
                break

    wanted = [key(a, m, cm) for a in AXES for m in models for cm in (False, True)]
    wanted += ["OnlineCapacityAnalytics|timeRemaining", "OnlineCapacityAnalytics|timeRemainingWithCommit"]
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   {"resourceId": [c[0] for c in clusters], "statKey": wanted})
    if st != 200:
        sys.exit(f"FATAL: stat query -> HTTP {st}")
    vals = {}
    for v in (body or {}).get("values") or []:
        d = {}
        for s in v.get("stat-list", {}).get("stat", []):
            k, data = s.get("statKey", {}).get("key"), (s.get("data") or [])
            if k and data:
                d[k] = data[-1]
        vals[v.get("resourceId")] = d

    print(f"ESTATE CAPACITY RUNWAY - {len(clusters)} cluster(s), {'/'.join(models)} model(s), "
          f"plain and commitment-adjusted")
    print(f"severity from {source}: critical under {crit:.0f}d, warning under {warn:.0f}d\n")
    head = "".join(f"{m[:4] + '.' + a[:4]:>11}" for m in models for a in AXES)
    print(f"  {'cluster':22}{head}{'runway':>9}")
    print("  " + "-" * (24 + 11 * len(models) * len(AXES) + 9))

    worst, exit_code, capped, divergent = None, 0, 0, 0
    rows = []
    for n, (rid, name) in enumerate(sorted(clusters, key=lambda c: c[1]), 1):
        d = vals.get(rid, {})
        cells, present = [], {}
        for m in models:
            for a in AXES:
                plain, commit = d.get(key(a, m, False)), d.get(key(a, m, True))
                if plain is not None and commit is not None and plain != commit:
                    divergent += 1
                v = commit if commit is not None else plain
                if v is not None:
                    present[f"{m}.{a}"] = v
                cells.append(days(v))
        runway = min(present.values()) if present else None
        # A cluster whose axes are all tied at the cap has no binding axis: min() would return
        # whichever key was inserted first, which reads as a measurement and is an artefact of
        # dict order. Report nothing rather than an arbitrary winner.
        tied = [ax for ax, v in present.items() if v == runway]
        binding = tied[0] if len(tied) == 1 else None
        if runway is not None and runway >= CAP_DAYS:
            capped += 1
        mark = ""
        if runway is not None:
            if runway < crit:
                mark, exit_code = "  CRITICAL", max(exit_code, 2)
            elif runway < warn:
                mark, exit_code = "  warning", max(exit_code, 1)
            if worst is None or runway < worst[0]:
                worst = (runway, name, binding)
        rows.append({"cluster": n, "binding": binding, "runwayDays": runway,
                     "atCap": runway is not None and runway >= CAP_DAYS})
        print(f"  {name:22}{''.join(f'{c:>11}' for c in cells)}{days(runway):>9}{mark}")
    print("  " + "-" * (24 + 11 * len(models) * len(AXES) + 9))

    if worst:
        wd, wn, wax = worst
        verdict = "CRITICAL" if wd < crit else ("warning" if wd < warn else "healthy")
        where = f"bound by {wn} on {wax}" if wax else f"bound by {wn}, with every axis tied"
        print(f"\n  ESTATE RUNWAY: {days(wd)}  ({verdict}) - {where}.")
        print("  First axis, first cluster: the estate can place projected demand this long before")
        print("  its tightest cluster runs out.")
    else:
        print("\n  no runway data yet (capacity analytics still computing for these clusters)")

    print(f"\n  {capped} of {len(clusters)} cluster(s) read the {CAP_DAYS}-day cap on every axis. A capped")
    print(f"  metric at its cap has no gradient: those clusters are indistinguishable here, and the")
    print(f"  read screens rather than ranks.")

    res = None
    print(f"\n  plain vs commitment-adjusted: {divergent} of {len(clusters) * len(models) * len(AXES)} "
          f"pair(s) differ.")
    if not divergent:
        res = reservation_census(tok)
        if res:
            print(f"  {res['withAReservation']} of {res['machines']} machine(s) carry a CPU or memory "
                  f"reservation, so the")
            print(f"  commitment-adjusted flavour has nothing to honour here. The pair is flat because of")
            print(f"  the estate, not because the distinction does not exist.")

    if record_path:
        # Clusters are numbered by their place in the sorted list; no cluster name is written.
        payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "clusters": len(clusters), "models": list(models), "axes": list(AXES),
                   "capDays": CAP_DAYS, "criticalDays": crit, "warningDays": warn,
                   "severitySource": source, "atCap": capped,
                   "pairsCompared": len(clusters) * len(models) * len(AXES),
                   "pairsDivergent": divergent, "reservations": res,
                   "estateRunwayDays": worst[0] if worst else None,
                   "boundBy": worst[2] if worst else None,
                   "rows": rows, "keysInFamily": len(AXES) * len(MODELS) * 2 + 2}
        with open(record_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=1) + "\n")
        for var in ("OPS_HOST", "OPS_BROKER_HOST"):
            v = os.environ.get(var)
            assert not v or v not in json.dumps(payload), f"{var} reached the record"
        print(f"\n  wrote {os.path.basename(record_path)}; clusters are numbered and none is named")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
