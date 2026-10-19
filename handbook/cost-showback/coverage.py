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
     is the other's roll-up. The family is every cost key collected on ANY object of the type, not
     the keys of the first object listed: one machine does not collect every key its type carries.

  2. COVERAGE, PER KEY. The gate. Not "are prices set" but "does THIS key report for the objects I
     am about to sum", which is the question that silently breaks a report. For the best- and
     worst-covered keys it also says whether the sparse key's objects are a subset of the dense
     key's, because only then does summing the sparse key simply drop the difference.

  3. COMPOSITION, TO THE CENT. A total that does not equal the sum of its published parts is a
     total you cannot explain to anyone. Checked on both models: the machine's daily cost against
     cpu plus memory plus storage plus additional, and the host's loaded cost against its seven
     named components. An object missing a part is counted apart, never summed as zero.

  4. WHETHER SHOWBACK IS A VIEW OR A BUILD. The tempting design is to roll priced signals up the
     custom-group tree that already scopes policies and alerts. Whether that works is a property of
     your instance: the run asks every group with members for its stat keys and counts the cost ones.

Read-only throughout: resource lists, stat keys, stat values, group membership. It prices nothing,
sets nothing, and writes nothing to the instance. A read that is refused or comes back short stops
the run (exit 4) rather than reporting an absence it did not observe.

Run:
  export OPS_HOST=... OPS_BROKER_HOST=... OPS_API_TOKEN_FILE=...   # mode 0600 (or OPS_API_TOKEN, the value)
  export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA
  python3 coverage.py                          # writes coverage.json beside this file (OUT_DIR to move it)

Exit: 0 composition holds on both models - 1 composition fails on a model - 4 a read failed or came back short
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from opslib import _ctx, bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

KINDS = ("VirtualMachine", "HostSystem", "ClusterComputeResource", "Datastore")
PAGE = 1000

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


def stop(msg):
    print(f"FATAL: {msg}; nothing is reported, because an absence this run did not observe would read as a finding")
    sys.exit(4)


def public(key):
    """A key as the record and the screen show it: a cost key named after something on your estate (an additional
    cost's own name, after a colon) is shown by its family only."""
    return key.split(":", 1)[0] + ":<name>" if ":" in key else key


def resources(tok, kind=None, path="/api/resources"):
    """Every object of a kind (or every member, for a group's members path), page by page, to the declared total."""
    out, page = [], 0
    while True:
        params = {"page": page, "pageSize": PAGE, "_no_links": "true"}
        if kind:
            params["resourceKind"] = kind
        st, body = ops("GET", path, tok, params=params)
        if st != 200:
            stop(f"list {kind or path} answered HTTP {st}")
        batch = (body or {}).get("resourceList") or []
        out += batch
        total = ((body or {}).get("pageInfo") or {}).get("totalCount")
        if total is None:
            stop(f"list {kind or path} declared no total")
        if len(out) >= total or not batch:
            break
        page += 1
    if len(out) != total:
        stop(f"list {kind or path} read {len(out)} of the {total} it declared")
    return [r for r in out if r.get("identifier")]


def statkeys(tok, rid):
    """The container is `stat-key`, hyphenated. A camel-case guess returns HTTP 200 and an empty
    list, which reads as an object that collects nothing rather than as a wrong key."""
    st, body = ops("GET", f"/api/resources/{rid}/statkeys", tok, params={"_no_links": "true"})
    if st != 200:
        stop(f"stat keys of one object answered HTTP {st}")
    return [k["key"] for k in ((body or {}).get("stat-key") or [])]


def described(tok, kind):
    """The cost keys the adapter describes for the object type, whether or not any object collects them."""
    st, body = ops("GET", f"/api/adapterkinds/VMWARE/resourcekinds/{kind}/statkeys", tok, params={"_no_links": "true"})
    if st != 200:
        return None
    return sorted(k["key"] for k in (body or {}).get("resourceTypeAttributes") or []
                  if (k.get("key") or "").startswith("cost|"))


def latest(tok, ids, keys):
    out = {}
    for i in range(0, len(ids), PAGE):
        st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                       {"resourceId": ids[i:i + PAGE], "statKey": keys})
        if st != 200:
            stop(f"the latest-stats query answered HTTP {st}")
        for v in (body or {}).get("values") or []:
            d = {}
            for s in v.get("stat-list", {}).get("stat", []):
                k, data = s.get("statKey", {}).get("key"), (s.get("data") or [])
                if k and data:
                    d[k] = data[-1]
            out[v.get("resourceId")] = d
    return out


def templates_among(tok, ids):
    """How many of these machines are templates, from the summary|config|isTemplate property; None when unread."""
    n = 0
    for i in range(0, len(ids), PAGE):
        st, body = ops("POST", "/api/resources/properties/latest/query", tok,
                       {"resourceIds": ids[i:i + PAGE], "propertyKeys": ["summary|config|isTemplate"]})
        if st != 200:
            return None
        for v in (body or {}).get("values") or []:
            for pc in v.get("property-contents", {}).get("property-content", []):
                if pc.get("statKey") == "summary|config|isTemplate" and (pc.get("values") or [None])[-1] == "true":
                    n += 1
    return n


def composition(vals, total_key, part_keys):
    """Does the total equal the sum of its published parts, on every object that reports a total and every part?"""
    checked = within = exact = missing = 0
    worst = 0.0
    for d in vals.values():
        if total_key not in d:
            continue
        if any(k not in d for k in part_keys):
            missing += 1
            continue
        checked += 1
        diff = abs(sum(d[k] for k in part_keys) - d[total_key])
        worst = max(worst, diff)
        exact += diff == 0
        within += diff < CENT
    return {"checked": checked, "withinACent": within, "exactToTheFloat": exact, "missingAPart": missing,
            "largestDifference": round(worst, 10), "passes": checked > 0 and within == checked}


def internal(tok, path):
    """One GET on VCF Operations' internal API, which answers only with the X-Ops-API-use-unsupported header and keeps
    no compatibility promise; (status, body or None)."""
    req = urllib.request.Request(f"https://{os.environ['OPS_HOST']}/suite-api{path}", headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/json", "X-Ops-API-use-unsupported": "true"})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
        return getattr(e, "code", None), None


def price_inputs(tok):
    """5. Which price inputs differ from the product's reference, and when the cost engine last ran. The cost-driver
    summary carries, per driver, the monthly cost in force and the reference cost the product computes; a driver whose
    two differ was entered or changed, one whose two match was left at the reference or entered at it. No amount is
    kept: only whether each driver matches."""
    st, summ = internal(tok, "/internal/costdrivers/summary")
    if st != 200 or not isinstance(summ, dict):
        return {"read": False, "status": st}
    drivers = [{"driver": c.get("costDriver"),
                "matchesReference": abs((c.get("totalCost") or 0.0) - (c.get("referenceTotalCost") or 0.0)) < CENT,
                "referenceIsZero": not c.get("referenceTotalCost")}
               for c in summ.get("summaryCostConfigurations") or []]
    _, modes = internal(tok, "/internal/costdrivers/configmodes")
    _, run = internal(tok, "/internal/costcalculation/status")
    run = run if isinstance(run, dict) else {}
    return {"read": True, "drivers": drivers,
            "modes": {m.get("costDriverType"): m.get("costDriverConfigModeType")
                      for m in (modes or {}).get("costDriverConfigModes") or []},
            "lastCalculation": {k: run.get(k) for k in ("status", "completionTime", "totalNoOfDatacenters",
                                                        "failedNoOfDatacenters")}}


def main():
    if sys.argv[1:]:
        sys.exit(f"unknown argument {sys.argv[1]}; coverage.py takes none (OUT_DIR moves the record)")
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    tok = bearer()
    print("coverage.py: what does this cost number actually cover?\n")

    # ---- the objects, and the cost keys each type actually collects
    objects, family, collected = {}, {}, {}
    for kind in KINDS:
        rl = resources(tok, kind)
        objects[kind] = [r["identifier"] for r in rl]
        keys = set()
        for rid in objects[kind]:
            keys |= {k for k in statkeys(tok, rid) if k.startswith("cost|")}
        desc = described(tok, kind)
        collected[kind] = sorted(keys)
        first = objects[kind] and {k for k in statkeys(tok, objects[kind][0]) if k.startswith("cost|")}
        family[kind] = {"objects": len(objects[kind]), "costKeysCollected": len(keys),
                        "costKeysDescribed": len(desc) if desc is not None else None,
                        "costKeysOnTheFirstObject": len(first) if objects[kind] else 0}

    # ---- 1. the family, per object type
    print("  1. THE FAMILY: cost keys collected on any object of the type, against the first object's own list")
    for kind in KINDS:
        f = family[kind]
        print(f"     {kind:<24} {f['costKeysCollected']:>3} collected across {f['objects']:>4} object(s); "
              f"{f['costKeysDescribed'] if f['costKeysDescribed'] is not None else '-':>3} described; "
              f"the first object alone shows {f['costKeysOnTheFirstObject']}")

    # ---- 2. coverage, per key
    coverage, vals_by_kind, spread = {}, {}, {}
    for kind in KINDS:
        keys, ids = collected[kind], objects[kind]
        vals = latest(tok, ids, keys) if ids and keys else {}
        vals_by_kind[kind] = vals
        per = {}
        for k in keys:
            rep = {rid for rid, d in vals.items() if k in d}
            per[k] = {"objects": len(ids), "reporting": len(rep), "nonZero": sum(1 for d in vals.values() if d.get(k)),
                      "_rep": rep}
        if not per:
            coverage[kind] = {}
            continue
        # Keys at each coverage level, densest first, each level checked against the densest: a key whose objects are
        # all among the densest key's drops the difference when summed; one that reports elsewhere covers other objects.
        top = max(per, key=lambda k: (per[k]["reporting"], k))
        levels = {}
        for k in per:
            levels.setdefault(per[k]["reporting"], []).append(k)
        spread[kind] = {"densest": public(top), "levels": [
            {"reporting": n, "keys": len(ks), "examples": [public(k) for k in sorted(ks)[:3]],
             "allWithinTheDensest": all(per[k]["_rep"] <= per[top]["_rep"] for k in ks)}
            for n, ks in sorted(levels.items(), reverse=True)]}
        print(f"\n  2. COVERAGE on {kind}: {len(ids)} object(s), {len(keys)} cost key(s), by how many objects each reports for")
        for lv in spread[kind]["levels"]:
            note = "" if lv["reporting"] == per[top]["reporting"] else (
                f"   within the densest key's objects: summing drops {per[top]['reporting'] - lv['reporting']}"
                if lv["allWithinTheDensest"] else "   reports for objects the densest key does not")
            print(f"     {lv['reporting']:>5}/{len(ids):<5} {lv['keys']:>3} key(s), e.g. {', '.join(lv['examples'][:2])}{note}")
        if kind == "VirtualMachine":
            unreached = [rid for rid in ids if rid not in per[top]["_rep"]]
            tpl = templates_among(tok, unreached) if unreached else 0
            spread[kind]["unreachedByTheDensest"] = len(unreached)
            spread[kind]["unreachedThatAreTemplates"] = tpl
            if unreached:
                print(f"     {len(unreached)} machine(s) no key reaches; {tpl if tpl is not None else '?'} of them are templates,"
                      " which carry no cost, so count machines, not templates, in the denominator")
        coverage[kind] = {public(k): {x: v for x, v in p.items() if x != "_rep"} for k, p in per.items()}

    # ---- 3. composition, both models
    comp = {"consumption": composition(vals_by_kind["VirtualMachine"], VM_TOTAL, VM_PARTS),
            "ownership": composition(vals_by_kind["HostSystem"], HOST_TOTAL, HOST_PARTS)}
    print("\n  3. COMPOSITION: does each total equal the sum of its published parts?")
    for name, c in comp.items():
        verdict = "PASSES" if c["passes"] else "FAILS"
        print(f"     {name:<13} {verdict}: {c['withinACent']}/{c['checked']} within a cent, largest difference "
              f"{c['largestDifference']:g}" + (f"; {c['missingAPart']} object(s) missing a part, not summed"
                                               if c["missingAPart"] else ""))

    # ---- 4. is showback a view or a build? every custom group with members, asked for its cost keys
    # The group list holds custom groups (the Container adapter's group types) and the product's own world objects
    # (vSphere World, VCF World and the like). A world object can carry estate-wide cost; that says nothing about
    # whether the groups you build carry it, so the two are counted apart.
    st, body = ops("GET", "/api/resources/groups", tok, params={"pageSize": 5000, "_no_links": "true"})
    if st != 200:
        stop(f"list custom groups answered HTTP {st}")
    groups = (body or {}).get("groups") or []
    total = ((body or {}).get("pageInfo") or {}).get("totalCount")
    if total is not None and total != len(groups):
        stop(f"list custom groups read {len(groups)} of the {total} it declared")
    custom = [g for g in groups if (g.get("resourceKey") or {}).get("adapterKindKey") == "Container"]
    worlds = [g for g in groups if g not in custom]
    populated = with_cost = members_priced = 0
    for g in custom:
        members = resources(tok, path=f"/api/resources/groups/{g['id']}/members")
        if not members:
            continue
        populated += 1
        if any(k.startswith("cost|") for k in statkeys(tok, g["id"])):
            with_cost += 1
        if {(m.get("resourceKey") or {}).get("resourceKindKey") for m in members} & set(KINDS):
            members_priced += 1
    world_cost = [(g.get("resourceKey") or {}).get("resourceKindKey") for g in worlds
                  if any(k.startswith("cost|") for k in statkeys(tok, g["id"]))]
    showback = {"groups": len(groups), "groupsDeclaredTotal": total, "customGroups": len(custom),
                "populatedCustomGroups": populated, "populatedCustomGroupsWithACostKey": with_cost,
                "populatedCustomGroupsWithPricedMembers": members_priced,
                "worldObjects": len(worlds), "worldObjectsWithCostKeys": sorted(world_cost),
                "isAView": populated > 0 and with_cost == populated}
    print(f"\n  4. SHOWBACK over the custom-group tree: {len(custom)} custom group(s), {populated} with members"
          + ("" if total is not None else " (the group list declares no total; it was read in one page of 5000)"))
    if populated:
        print(f"     {with_cost} of the {populated} with members carry a cost key; {members_priced} of them hold "
              f"members of a priced type")
        print("     " + ("cost rolls up the group tree: showback is a view" if showback["isAView"] else
                         "the custom groups do not carry cost: showback is a build, not a view. Aggregate over members"
                         " deliberately (a super metric that sums the members' cost), and say so rather than pointing"
                         " at an existing tree."))
    else:
        print("     no custom group has members to test against; stand one up before designing showback on it")
    print(f"     the product's own world objects: {len(world_cost)} of {len(worlds)} carry cost keys"
          + (f" ({', '.join(sorted(world_cost))}), the estate-wide totals, not a showback by your groups"
             if world_cost else ""))

    # ---- 5. the price inputs: which differ from the reference, and when the cost engine last ran
    st, cur = ops("GET", "/api/costconfig/currency", tok, params={"_no_links": "true"})
    currency = (cur or {}).get("code") if st == 200 else None
    prices = price_inputs(tok)
    print(f"\n  5. PRICE INPUTS (currency {currency or 'not served'}): the public API serves the currency only; the internal")
    print("     cost-driver summary carries each driver's cost in force beside the product's reference")
    if prices["read"]:
        changed = [d["driver"] for d in prices["drivers"] if not d["matchesReference"]]
        same = [d["driver"] for d in prices["drivers"] if d["matchesReference"]]
        print(f"     {len(changed)} of {len(prices['drivers'])} driver(s) differ from the reference, so were entered or "
              f"changed: {', '.join(changed) or 'none'}")
        print(f"     {len(same)} match it, left at the reference or entered at it: {', '.join(same) or 'none'}")
        lc = prices["lastCalculation"]
        print(f"     the cost engine last ran {lc.get('status') or '?'} at {lc.get('completionTime') or '?'} (the "
              f"instance's own clock and format), {lc.get('failedNoOfDatacenters')} of "
              f"{lc.get('totalNoOfDatacenters')} datacenter(s) failed; print this beside every figure")
    else:
        print(f"     the internal summary was not read (HTTP {prices['status']}): confirming the inputs is a person's step")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "family": family, "coverage": coverage, "spread": spread, "composition": comp,
               "showback": showback, "currency": currency, "priceInputs": prices,
               "vmKeys": [public(k) for k in collected["VirtualMachine"]],
               "hostKeys": [public(k) for k in collected["HostSystem"]]}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    for kind in KINDS:
        for k in collected[kind]:
            if ":" in k:
                assert k.split(":", 1)[1] not in text, "an estate-named cost key reached the record"
    # No object is named anywhere in this record: it carries key names and counts only.
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "coverage.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nwrote coverage.json; it carries key names and counts, and names no object")
    return 0 if all(c["passes"] for c in comp.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
