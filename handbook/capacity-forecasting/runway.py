#!/usr/bin/env python3
"""runway.py - the estate capacity runway, rolled up the way the sheet teaches.

Reads time remaining in days per resource axis per cluster, then rolls up pessimistically, under each capacity model
separately: a cluster's runway is its first axis to run out, and the estate's runway is its first cluster. The number
is always reported with its model, its cluster and its axis attached, and every cluster tied at the minimum is named.

What it does that a single-number read does not:

  THE FAMILY, NOT A KEY. Time remaining is three axes by two capacity models (allocation and demand) by two flavours
  (plain, and commitment-adjusted), plus the platform's own per-cluster roll-up, fourteen keys in one stats query. The
  allocation model asks when configured capacity runs out and the demand model asks when observed demand does, so the
  run rolls each model up on its own line. The platform's roll-up key is the minimum across all six axis-model pairs:
  it says how soon, never under which model, so the run prints it as a cross-check beside the per-model figures.

  THE CAP. The platform caps time remaining at one year. A cluster reading the cap is past the horizon the metric
  measures, and every cluster at the cap reads identically, so the run prints how many clusters are pinned there.

  THE RULER EACH CLUSTER IS MEASURED AGAINST. Each cluster is projected against the policy that governs it, read
  through the effective-policy query, and graded by that policy's own TIME_REMAINING thresholds. For every governing
  policy the run prints its three capacity blocks (allocation ratios, buffers, thresholds), each with the `inherited`
  flag that says whether the policy sets the value or the default shows through. --parity compares PARSED ratios
  against declared ones, never substrings against serialized JSON.

  WHOLE READS OR NONE. The cluster and machine lists are read page by page to their declared totals; a read that is
  refused or comes back short stops the run (exit 4) rather than projecting a partial estate.

Usage:  python3 runway.py [--parity expectations.json] [--parity-warn] [--model alloc|demand|both]
                          [--record runway.json]
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN_FILE or OPS_API_TOKEN, ...)
Exit:   0 healthy - 1 warning - 2 critical - 3 parity gate refused - 4 a read the run needs failed or came back short
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from opslib import _ctx, bearer, ops

AXES = ("cpu", "mem", "diskspace")
MODELS = ("alloc", "demand")
CAP_DAYS = 366          # the platform caps time remaining at one year; verified live
FALLBACK_CRIT, FALLBACK_WARN = 30, 90   # used only when a cluster's governing policy could not be read
KINDS = {"resourceKind": "ClusterComputeResource", "adapterKind": "VMWARE"}
SETTINGS_BASE = dict(KINDS, includeInherited="true", _no_links="true")
PAGE = 1000


def key(axis, model, commit):
    return (f"OnlineCapacityAnalytics|{axis}|{model}|"
            + ("timeRemainingWithCommit" if commit else "timeRemaining"))


ROLLUP = ("OnlineCapacityAnalytics|timeRemaining", "OnlineCapacityAnalytics|timeRemainingWithCommit")


def days(v):
    if v is None:
        return "-"
    return "cap" if v >= CAP_DAYS else f"{v:.0f}d"


def short(v):
    return "cap" if v is not None and v >= CAP_DAYS else ("-" if v is None else f"{v:g}")


def read_whole(tok, params, what):
    """Every resource of a kind, page by page, to the declared total; exit 4 on a refusal or a short read."""
    out, page = [], 0
    while True:
        st, body = ops("GET", "/api/resources", tok, params=dict(params, page=page, pageSize=PAGE, _no_links="true"))
        if st != 200:
            print(f"FATAL: list {what} -> HTTP {st}")
            sys.exit(4)
        batch = (body or {}).get("resourceList") or []
        out += batch
        total = ((body or {}).get("pageInfo") or {}).get("totalCount")
        if total is None:
            print(f"FATAL: list {what} declared no total, so a short read could not be told from a whole one")
            sys.exit(4)
        if len(out) >= total or not batch:
            break
        page += 1
    if len(out) != total:
        print(f"FATAL: list {what} read {len(out)} of the {total} it declared")
        sys.exit(4)
    return out


def effective_policies(tok, ids):
    """Each resource id's governing policy id, through the effective-policy query (VCF Operations' internal API,
    which needs one X-Ops-API-use-unsupported header), or None when the query is refused."""
    req = urllib.request.Request(
        f"https://{os.environ['OPS_HOST']}/suite-api/internal/policies/effective/query",
        data=json.dumps({"resourceIds": list(ids)}).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json",
                 "Content-Type": "application/json", "X-Ops-API-use-unsupported": "true"})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r:
            payload = json.loads(r.read() or b"null")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        return None
    out = {}
    for entry in (payload or {}).get("effectivePolicies") or []:
        for rid in entry.get("resourceIds") or []:
            out[rid] = entry.get("policyId")
    return out


def settings(tok, pid, stype):
    """One settings block. `type` is REQUIRED (the endpoint answers 400 without it) and it selects which block comes
    back: CAPACITY_ALLOCATION_MODEL the overcommit ratios, CAPACITY_BUFFER the buffers, TIME_REMAINING the
    criticality thresholds."""
    st, body = ops("GET", f"/api/policies/{pid}/settings", tok, params=dict(SETTINGS_BASE, type=stype))
    return (body or {}) if st == 200 else None


def blocks_of(tok, pid):
    """The three capacity blocks of one policy, each (value, inherited) or (None, None) when unread. Parsed, never
    string-matched."""
    out = {}
    body = settings(tok, pid, "CAPACITY_ALLOCATION_MODEL")
    rows = ((body or {}).get("capacitySettings", {}).get("capacity", {}).get("capacityAllocationSettings") or [])
    out["ratios"] = ((rows[0].get("capacityAllocation") or {}), rows[0].get("inherited")) if rows else (None, None)
    body = settings(tok, pid, "CAPACITY_BUFFER")
    rows = ((body or {}).get("capacitySettings", {}).get("capacity", {}).get("capacityBufferSettings") or [])
    out["buffers"] = ((rows[0].get("capacityBuffer") or {}), rows[0].get("inherited")) if rows else (None, None)
    body = settings(tok, pid, "TIME_REMAINING")
    rows = ((body or {}).get("capacitySettings", {}).get("criticalityThresholds", {})
            .get("timeRemainingSettings") or [])
    if rows:
        cfg = rows[0].get("criticalityThresholdsConfig") or {}
        out["thresholds"] = ({"critical": cfg.get("critical"), "warning": cfg.get("warning")}, rows[0].get("inherited"))
    else:
        out["thresholds"] = (None, None)
    return out


def policy_names(tok):
    st, body = ops("GET", "/api/policies", tok, params={"pageSize": 500, "_no_links": "true"})
    if st != 200:
        print(f"FATAL: list policies -> HTTP {st}")
        sys.exit(4)
    return {p["id"]: p["name"] for p in (body or {}).get("policySummaries", [])}


def parity_gate(tok, path, warn_only, names):
    """Refuse the runway when a declared policy's PARSED allocation ratios differ from the declared ones.
    Expectations: {"<policy name>": {"cpu": 1.5, "memory": 1.0, "diskspace": 2.0}}.

    Comparing parsed numbers is the whole point: a substring test over serialized settings passes "cpu": 1 against a
    ruler that reads 15.0, and refuses "cpu":1.5 against a ruler that reads exactly 1.5 because the serializer puts a
    space after the colon.
    """
    with open(path, encoding="utf-8") as fh:
        declared = {k: v for k, v in json.load(fh).items() if not k.startswith("comment")}
    by_name = {n: i for i, n in names.items()}
    failures, notes = [], []
    for pname, want in declared.items():
        pid = by_name.get(pname)
        if pid is None:
            failures.append(f"policy not found: {pname}")
            continue
        got, inherited = blocks_of(tok, pid)["ratios"]
        if got is None:
            failures.append(f"{pname}: no allocation model in the policy's settings read")
            continue
        if inherited:
            notes.append(f"{pname}: the allocation model is INHERITED, so this policy does not set it; you are "
                         f"verifying the default showing through")
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
            print("a drifted ruler looks precise and reads wrong; fix the policy or the expectation before trusting "
                  "any projection.")
            sys.exit(3)
    else:
        print(f"parity gate: {len(declared)} policy(ies) match their declared ratios exactly\n")


def reservation_census(tok):
    """How many machines carry a CPU or memory reservation. Without one, the commitment-adjusted flavour has nothing
    to honour and reads identically to the plain one, which is a fact about the estate and not about the metric."""
    ids = [r["identifier"] for r in read_whole(tok, {"resourceKind": "VirtualMachine"}, "machines")]
    n = 0
    for i in range(0, len(ids), PAGE):
        st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                       {"resourceId": ids[i:i + PAGE], "statKey": ["config|memoryAllocation|reservation",
                                                                   "config|cpuAllocation|reservation"]})
        if st != 200:
            return None
        for v in (body or {}).get("values") or []:
            for s in v.get("stat-list", {}).get("stat", []):
                data = s.get("data") or []
                if data and data[-1]:
                    n += 1
                    break
    return {"machines": len(ids), "withAReservation": n}


def main():
    argv = sys.argv[1:]
    known = {"--parity", "--parity-warn", "--model", "--record"}
    for a in argv:
        if a.startswith("--") and a not in known:
            sys.exit(f"unknown argument {a}; see the usage in this file's docstring")
    parity_file = argv[argv.index("--parity") + 1] if "--parity" in argv else None
    model_arg = argv[argv.index("--model") + 1] if "--model" in argv else "both"
    record_path = argv[argv.index("--record") + 1] if "--record" in argv else None
    if model_arg not in ("alloc", "demand", "both"):
        sys.exit("--model takes alloc, demand or both")
    models = MODELS if model_arg == "both" else (model_arg,)
    tok = bearer()
    names = policy_names(tok)
    if parity_file:
        parity_gate(tok, parity_file, "--parity-warn" in argv, names)

    clusters = sorted(((r["identifier"], r["resourceKey"]["name"]) for r in read_whole(tok, KINDS, "clusters")
                       if r.get("identifier")), key=lambda c: c[1])
    if not clusters:
        sys.exit("no clusters visible to this token; nothing to project")

    # The ruler each cluster is measured against: its governing policy, and that policy's three blocks.
    eff = effective_policies(tok, [c[0] for c in clusters])
    governing = {}                       # policy id -> its blocks
    if eff is not None:
        for pid in dict.fromkeys(eff.get(c[0]) for c in clusters):
            if pid:
                governing[pid] = blocks_of(tok, pid)
    pnum = {pid: n for n, pid in enumerate(governing, 1)}

    wanted = [key(a, m, cm) for a in AXES for m in MODELS for cm in (False, True)] + list(ROLLUP)
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   {"resourceId": [c[0] for c in clusters], "statKey": wanted})
    if st != 200:
        print(f"FATAL: stat query -> HTTP {st}")
        sys.exit(4)
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
    print("\n  THE RULER - each cluster's governing policy, read through the effective-policy query")
    if eff is None:
        print("  the effective-policy query was refused: no cluster's ruler was read, and severity falls back to")
        print(f"  this script's constants (critical under {FALLBACK_CRIT}d, warning under {FALLBACK_WARN}d)")
    for pid, b in governing.items():
        r, ri = b["ratios"]
        bu, bi = b["buffers"]
        t, ti = b["thresholds"]
        governed = sum(1 for c in clusters if eff.get(c[0]) == pid)
        flag = lambda inh: "unread" if inh is None else ("inherited" if inh else "set here")  # noqa: E731
        print(f"  policy {pnum[pid]}  {names.get(pid, '(unnamed)')}  governs {governed} cluster(s)")
        print("    allocation ratios  " + (f"cpu {short(r.get('cpu'))}, memory {short(r.get('memory'))}, "
                                            f"diskspace {short(r.get('diskspace'))}" if r else "-") + f"  ({flag(ri)})")
        bufs = sorted({v for ax in (bu or {}).values() if isinstance(ax, dict) for v in ax.values()})
        print("    buffers            " + (", ".join(f"{x:g}" for x in bufs) if bu else "-")
              + f"  ({flag(bi)})")
        print("    thresholds         " + (f"critical {short(t.get('critical'))}d, warning {short(t.get('warning'))}d"
                                            if t else "-") + f"  ({flag(ti)})")

    head = "".join(f"{m[:4] + '.' + a[:4]:>11}" for m in models for a in AXES)
    print(f"\n  {'cluster':22}{'pol':>4}{head}" + "".join(f"{m[:4] + ' runway':>13}" for m in models)
          + f"{'platform':>10}")
    rule = "  " + "-" * (26 + 11 * len(models) * len(AXES) + 13 * len(models) + 10)
    print(rule)

    capped, divergent, rows, exit_code = 0, 0, [], 0
    for n, (rid, name) in enumerate(clusters, 1):
        d = vals.get(rid, {})
        pid = (eff or {}).get(rid)
        t = (governing.get(pid) or {}).get("thresholds", (None, None))[0] or {}
        crit = t.get("critical") if t.get("critical") is not None else FALLBACK_CRIT
        warn = t.get("warning") if t.get("warning") is not None else FALLBACK_WARN
        cells, per_model, every = [], {}, []
        for m in models:
            present = {}
            for a in AXES:
                plain, commit = d.get(key(a, m, False)), d.get(key(a, m, True))
                if plain is not None and commit is not None and plain != commit:
                    divergent += 1
                v = commit if commit is not None else plain
                if v is not None:
                    present[a] = v
                cells.append(days(v))
            runway = min(present.values()) if present else None
            # A cluster whose axes are tied at its minimum has no single binding axis: min() would return whichever
            # key came first, which reads as a measurement and is an artefact of order. Name every tied axis instead.
            tied = sorted(a for a, v in present.items() if v == runway) if present else []
            per_model[m] = {"runwayDays": runway, "binding": tied if len(tied) < len(present) else [],
                            "atCap": runway is not None and runway >= CAP_DAYS}
            every += list(present.values())
        if every and min(every) >= CAP_DAYS:
            capped += 1
        sev = 0
        for m in models:
            rw = per_model[m]["runwayDays"]
            if rw is not None:
                sev = max(sev, 2 if rw < crit else (1 if rw < warn else 0))
        exit_code = max(exit_code, sev)
        platform = d.get(ROLLUP[1], d.get(ROLLUP[0]))
        mark = {2: "  CRITICAL", 1: "  warning"}.get(sev, "")
        print(f"  {name:22}{(str(pnum[pid]) if pid in pnum else '-'):>4}{''.join(f'{c:>11}' for c in cells)}"
              + "".join(f"{days(per_model[m]['runwayDays']):>13}" for m in models) + f"{days(platform):>10}{mark}")
        rows.append({"cluster": n, "policy": pnum.get(pid), "criticalDays": crit, "warningDays": warn,
                     "models": per_model, "platformRollupDays": platform,
                     "keysReturned": sum(1 for k in wanted if k in d), "severity": ["healthy", "warning", "critical"][sev]})
    print(rule)

    estate = {}
    for m in models:
        known_rows = [r for r in rows if r["models"][m]["runwayDays"] is not None]
        if not known_rows:
            print(f"\n  {m.upper()} RUNWAY: no data yet (capacity analytics still computing for these clusters)")
            continue
        low = min(r["models"][m]["runwayDays"] for r in known_rows)
        at = [r for r in known_rows if r["models"][m]["runwayDays"] == low]
        estate[m] = {"runwayDays": low, "atCap": low >= CAP_DAYS,
                     "boundBy": [{"cluster": r["cluster"], "axes": r["models"][m]["binding"]} for r in at]}
        if low >= CAP_DAYS:
            print(f"\n  {m.upper()} RUNWAY: cap on every cluster - past the horizon the metric measures, so it screens"
                  f" clean and ranks nothing")
            continue
        where = "; ".join(f"{clusters[r['cluster'] - 1][1]} on "
                          + (", ".join(f"{m}.{a}" for a in r["models"][m]["binding"]) or "every axis, tied")
                          for r in at)
        print(f"\n  {m.upper()} RUNWAY: {days(low)} - bound by {where}")
    print("  First axis, first cluster, per model: how long each question's answer lasts before the tightest cluster")
    print("  runs out. The platform column is its own roll-up, the minimum across both models.")

    print(f"\n  {capped} of {len(clusters)} cluster(s) read the {CAP_DAYS}-day cap on every axis. A capped metric at its")
    print("  cap has no gradient: those clusters are indistinguishable here, and the read screens rather than ranks.")

    res = None
    pairs = len(clusters) * len(models) * len(AXES)
    print(f"\n  plain vs commitment-adjusted: {divergent} of {pairs} pair(s) differ.")
    if not divergent:
        res = reservation_census(tok)
        if res:
            print(f"  {res['withAReservation']} of {res['machines']} machine(s) carry a CPU or memory reservation, so "
                  f"the")
            print("  commitment-adjusted flavour has nothing to honour here. The pair is flat because of the estate,")
            print("  not because the distinction does not exist.")

    if record_path:
        # Clusters and policies are numbered; no cluster or policy name is written.
        payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "clusters": len(clusters), "models": list(models), "axes": list(AXES), "capDays": CAP_DAYS,
                   "keysInFamily": len(AXES) * len(MODELS) * 2 + 2, "keysAsked": len(wanted),
                   "effectivePolicyRead": eff is not None,
                   "policies": [{"policy": pnum[pid], "governs": sum(1 for c in clusters if (eff or {}).get(c[0]) == pid),
                                 "builtInDefault": names.get(pid) == "Default Policy",
                                 "ratios": b["ratios"][0], "ratiosInherited": b["ratios"][1],
                                 "buffers": b["buffers"][0], "buffersInherited": b["buffers"][1],
                                 "thresholds": b["thresholds"][0], "thresholdsInherited": b["thresholds"][1]}
                                for pid, b in governing.items()],
                   "atCap": capped, "pairsCompared": pairs, "pairsDivergent": divergent, "reservations": res,
                   "estate": estate, "rows": rows, "exit": exit_code}
        text = json.dumps(payload, indent=1) + "\n"
        for var in ("OPS_HOST", "OPS_BROKER_HOST"):
            v = os.environ.get(var)
            assert not v or v not in text, f"{var} reached the record"
        for _, nm in clusters:
            assert nm not in text, "a cluster name reached the record"
        for nm in names.values():
            assert f'"{nm}"' not in text, "a policy name reached the record"
        with open(record_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\n  wrote {os.path.basename(record_path)}; clusters and policies are numbered and none is named")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
