#!/usr/bin/env python3
"""coverage.py: before you believe a cost number, find out what it covers.

A cost metric computes whether or not anyone set the prices, and it computes whether or not it has
anything to say about the object you are about to sum. So the first question about a cost figure is
never "how much" but "over what", and this answers it read-only, from the outputs rather than from a
settings page.

It reports four things:

  1. THE FAMILY, PER OBJECT TYPE. Cost is not one metric and it is not one vocabulary. A virtual
     machine carries a CONSUMPTION model: three bases (allocation-based, demand-based, and the
     effective one actually in force) across cpu, memory and storage, daily and month-to-date. A
     host carries an OWNERSHIP model: hardware, facilities, labour, network, maintenance, OS
     licensing, depreciation, and their loaded total. These answer different questions and neither
     is the other's roll-up.

  2. COVERAGE, PER KEY. The gate. Not "are prices set" but "does THIS key report for the objects I
     am about to sum", which is a different question and the one that silently breaks a report: on
     the estate this was written against, one daily-cost key covered 91 of 103 machines while its
     basis-specific sibling covered 22, and the 22 were a strict subset. Summing the sparse key
     produces a confident number that is missing four fifths of the estate.

  3. COMPOSITION, TO THE DECIMAL. A total that does not equal the sum of its published parts is a
     total you cannot explain to anyone. Checked on both models: the machine's daily cost against
     cpu plus memory plus storage plus additional, and the host's loaded cost against its seven
     named components.

  4. WHETHER SHOWBACK IS A VIEW OR A BUILD. The tempting design is to roll priced signals up the
     custom-group tree that already scopes policies and alerts. Whether that works is a property of
     your instance, and it is one read: ask a group with members for its stat keys and count the
     cost ones.

Read-only throughout: resource lists, stat keys, stat values, group membership. It prices nothing,
sets nothing, and writes nothing to the instance.

Run:
  export OPS_HOST=... OPS_BROKER_HOST=... OPS_API_TOKEN=...
  export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA
  python3 coverage.py                          # writes coverage.json beside this file
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from opslib import bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

KINDS = ("VirtualMachine", "HostSystem", "ClusterComputeResource", "Datastore")

# The machine's daily cost and the parts it is published as.
VM_TOTAL = "cost|effectiveDailyCost"
VM_PARTS = ["cost|effectiveDailyCpuCost", "cost|effectiveDailyMemoryCost",
            "cost|effectiveDailyStorageCost", "cost|dailyAdditionalCost"]
# The host's loaded cost and the components it is published as.
HOST_TOTAL = "cost|totalLoadedCost"
HOST_PARTS = ["cost|hardwareTotalCost", "cost|facilitiesTotalCost", "cost|hostLaborTotalCost",
              "cost|networkTotalCost", "cost|maintenanceTotalCost", "cost|hostOslTotalCost",
              "cost|additionalTotalCost"]
CENT = 0.01


def resources(tok, kind, page=2000):
    st, body = ops("GET", "/api/resources", tok,
                   params={"resourceKind": kind, "pageSize": page, "_no_links": "true"})
    if st != 200:
        return []
    return [r for r in ((body or {}).get("resourceList") or []) if r.get("identifier")]


def statkeys(tok, rid):
    """The container is `stat-key`, hyphenated. A camel-case guess returns HTTP 200 and an empty
    list, which reads as an object that collects nothing rather than as a wrong key."""
    st, body = ops("GET", f"/api/resources/{rid}/statkeys", tok, params={"_no_links": "true"})
    return [k["key"] for k in ((body or {}).get("stat-key") or [])] if st == 200 else []


def latest(tok, ids, keys):
    out = {}
    if not ids or not keys:
        return out
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   {"resourceId": ids, "statKey": keys})
    if st != 200:
        return out
    for v in (body or {}).get("values") or []:
        d = {}
        for s in v.get("stat-list", {}).get("stat", []):
            k, data = s.get("statKey", {}).get("key"), (s.get("data") or [])
            if k and data:
                d[k] = data[-1]
        out[v.get("resourceId")] = d
    return out


def composition(vals, total_key, part_keys):
    """Does the total equal the sum of its published parts, on every object that reports a total?"""
    checked = within = exact = 0
    worst = 0.0
    for d in vals.values():
        if total_key not in d:
            continue
        checked += 1
        diff = abs(sum(d.get(k, 0.0) for k in part_keys) - d[total_key])
        worst = max(worst, diff)
        if diff == 0:
            exact += 1
        if diff < CENT:
            within += 1
    return {"checked": checked, "withinACent": within, "exactToTheFloat": exact,
            "largestDifference": round(worst, 10),
            "passes": checked > 0 and within == checked}


def main():
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    tok = bearer()
    print("coverage.py: what does this cost number actually cover?\n")

    # ---- 1. the family, per object type
    family, sample = {}, {}
    for kind in KINDS:
        rl = resources(tok, kind, page=5)
        if not rl:
            family[kind] = {"objects": 0, "costKeys": 0}
            continue
        keys = statkeys(tok, rl[0]["identifier"])
        cost = sorted(k for k in keys if k.startswith("cost|"))
        family[kind] = {"statKeys": len(keys), "costKeys": len(cost)}
        sample[kind] = cost
    print("  1. THE FAMILY: cost keys on the object type, which is not the same as cost data")
    for kind in KINDS:
        f = family[kind]
        print(f"     {kind:<24} {f.get('costKeys', 0):>3} cost key(s) of {f.get('statKeys', 0):>4}")

    # ---- 2. coverage, per key, on the two models that carry data
    coverage, models = {}, {}
    for kind in KINDS:
        keys = sample.get(kind, [])
        rl = resources(tok, kind)
        ids = [r["identifier"] for r in rl]
        vals = latest(tok, ids, keys)
        per = {}
        for k in keys:
            reporting = sum(1 for d in vals.values() if k in d)
            nonzero = sum(1 for d in vals.values() if d.get(k))
            per[k] = {"objects": len(ids), "reporting": reporting, "nonZero": nonzero}
        coverage[kind] = per
        models[kind] = {"objects": len(ids), "vals": vals}
        if not keys or not ids:
            continue
        best = max(per.values(), key=lambda x: x["reporting"])["reporting"]
        worst = min(per.values(), key=lambda x: x["reporting"])["reporting"]
        print(f"\n  2. COVERAGE on {kind}: {len(ids)} object(s), {len(keys)} cost key(s)")
        print(f"     best-covered key reports for {best}, worst-covered for {worst}")
        if best and worst < best:
            print(f"     the spread is the finding: summing the sparse key silently drops "
                  f"{best - worst} object(s)")
        for k in sorted(per, key=lambda x: -per[x]["reporting"])[:4]:
            print(f"       {k:<52} {per[k]['reporting']:>4}/{per[k]['objects']}")
        if len(per) > 4 and worst < best:
            # Only worth printing when there IS a spread; on a uniformly covered object type the
            # "worst" key is just another row already shown above.
            k = min(per, key=lambda x: per[x]["reporting"])
            print(f"       {'...':<52}")
            print(f"       {k:<52} {per[k]['reporting']:>4}/{per[k]['objects']}")

    # ---- 3. composition, both models
    vm_vals = models.get("VirtualMachine", {}).get("vals", {})
    host_vals = models.get("HostSystem", {}).get("vals", {})
    comp = {"consumption": composition(vm_vals, VM_TOTAL, VM_PARTS),
            "ownership": composition(host_vals, HOST_TOTAL, HOST_PARTS)}
    print("\n  3. COMPOSITION: does each total equal the sum of its published parts?")
    for name, c in comp.items():
        verdict = "PASSES" if c["passes"] else "FAILS"
        print(f"     {name:<13} {verdict}: {c['withinACent']}/{c['checked']} within a cent, "
              f"largest difference {c['largestDifference']:g}")

    # ---- 4. is showback a view or a build?
    st, body = ops("GET", "/api/resources/groups", tok,
                   params={"pageSize": 500, "_no_links": "true"})
    groups = ((body or {}).get("groups") or []) if st == 200 else []
    populated, gkeys, gcost = None, 0, 0
    for g in groups:
        st, b2 = ops("GET", "/api/resources", tok,
                     params={"parentId": g["id"], "pageSize": 1, "_no_links": "true"})
        if st == 200 and ((b2 or {}).get("pageInfo") or {}).get("totalCount"):
            populated = g["id"]
            break
    if populated:
        ks = statkeys(tok, populated)
        gkeys, gcost = len(ks), len([k for k in ks if k.startswith("cost|")])
    showback = {"groups": len(groups), "populatedGroupFound": bool(populated),
                "groupStatKeys": gkeys, "groupCostKeys": gcost,
                "isAView": bool(populated) and gcost > 0}
    print(f"\n  4. SHOWBACK over the custom-group tree: {len(groups)} group(s)")
    if populated:
        print(f"     a group with members carries {gkeys} stat key(s), of which {gcost} are cost keys")
        print("     " + ("cost rolls up the group tree: showback is a view"
                         if gcost else
                         "the group tree carries NO cost: showback is a build, not a view. Aggregate"
                         " over members deliberately (a super metric that sums the members' cost),"
                         " and say so rather than pointing at an existing tree."))
    else:
        print("     no populated group to test against; stand one up before designing showback on it")

    # ---- the currency, which is the one pricing fact the suite API serves on this build
    st, cur = ops("GET", "/api/costconfig/currency", tok, params={"_no_links": "true"})
    currency = (cur or {}).get("code") if st == 200 else None
    print(f"\n  currency: {currency or 'not served'}. The price inputs themselves are not on this "
          f"API surface here,")
    print(f"  which is why this gate measures coverage from the outputs rather than reading a "
          f"settings page.")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "family": family, "coverage": coverage, "composition": comp,
               "showback": showback, "currency": currency,
               "vmKeys": sample.get("VirtualMachine", []),
               "hostKeys": sample.get("HostSystem", [])}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    # No object is named anywhere in this record: it carries key names and counts only.
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "coverage.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nwrote coverage.json; it carries key names and counts, and names no object")
    return 0


if __name__ == "__main__":
    sys.exit(main())
