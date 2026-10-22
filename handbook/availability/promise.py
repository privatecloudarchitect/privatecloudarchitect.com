#!/usr/bin/env python3
"""promise.py: is your availability arm still computing, and what does it currently say?

The rest of this folder stands the arm up. This reads it back. A computed promise is the kind of thing that
is verified once on the day it ships and never again, and the three ways it quietly stops being true are all
readable:

  1. THE CONTENT IS STILL THERE. The five reachability super metrics, found by name, with the formula each
     one currently carries. Content gets edited, re-imported and rebuilt, and a formula that changed is a
     promise that changed;
  2. IT IS STILL COMPUTING. The current value of every one of them on the ping adapter instance, each with
     the AGE of the reading. A value with no timestamp is not evidence that anything is computing, and a
     fleet of readings that all stopped at the same age is one dead collector rather than a fleet of
     failures;
  3. AND THE DENOMINATOR IS WHAT YOU THINK. The adapter's direct children against the raw object count. An
     FQDN check's resolved address is a child of the check, not of the instance, so counting objects instead
     of depth-1 children inflates the denominator and understates the SLI. This reads the relationship tree
     and shows the arithmetic.

It then reports the shape of the failure rather than only its size. Checks are grouped by address block,
anonymised, because five unreachable endpoints spread across three blocks is five problems and five in one
block is one cause to find (a routing boundary, or front doors retired together), and a percentage cannot
tell those apart.

Finally it crosses the guest layer against the floor beneath it: every virtual machine's guest availability
KPI, which rides VMware Tools, against what the hypervisor says without Tools, its power state and the age of
its uptime reading. A KPI of zero on a powered-off machine is down, or off on purpose; on a powered-on machine
with a current uptime it is a blind reading, not a down machine; and a resource whose adapter reports
NOT_EXISTING is a deleted machine's record, which keeps its last values and is not a machine at all. A
powered-off machine keeps its last uptime, so the uptime's age, not its value, says whether it is running.

Read-only throughout. Nothing here imports, edits or deletes content.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_REALM=CUSTOMER
  export OPS_API_TOKEN_FILE=<api-token file>      # mode 0600 (or OPS_API_TOKEN, the value itself)
  export OPS_OWNER="PCA"                          # the owner prefix your content carries
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 promise.py
"""

import collections
import datetime as dt
import json
import os
import re
import time

from opslib import bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# The reachability arm, by the role each metric plays rather than by its full published name, so the script
# finds them on an estate that names the bundle (the name's second field) differently.
FRESH_MINUTES = 30   # an uptime reading older than this is not evidence the machine is running now

ROLES = [("checks", "Checks (count)"), ("reachable", "Checks Reachable"), ("unreachable", "Checks Unreachable"),
         ("sli", "Reachability SLI"), ("delivery", "Packet Delivery")]


def latest(resource_id, tok, now):
    """Every current stat on one object as {key: (value, age in minutes)}."""
    st, body = ops("GET", f"/api/resources/{resource_id}/stats/latest", tok, params={"_no_links": "true"})
    out = {}
    for v in ((body.get("values") or []) if isinstance(body, dict) else []):
        for s in (v.get("stat-list") or {}).get("stat", []):
            data, stamps = s.get("data") or [], s.get("timestamps") or []
            if data and stamps:
                age = round((now - dt.datetime.fromtimestamp(stamps[-1] / 1000, dt.timezone.utc)
                             ).total_seconds() / 60, 1)
                out[s["statKey"]["key"]] = (data[-1], age)
    return out


def block_of(name):
    """An anonymised label for the address block a check sits in.

    The block matters and the address does not: five unreachable endpoints in one block is one cause to
    find, and the same five spread across three blocks is five problems.
    """
    m = re.match(r"^(\d{1,3})\.(\d{1,3})\.", str(name or ""))
    return f"{m.group(1)}.{m.group(2)}" if m else None


def main():
    owner = os.environ.get("OPS_OWNER", "PCA")
    out_dir = os.environ.get("OUT_DIR", ".")
    tok = bearer()
    now = dt.datetime.now(dt.timezone.utc)
    print("promise.py: is the availability arm still computing, and what does it say?\n")

    # ---- 1: the content is still there
    sms, n = [], 0
    while True:
        st, body = ops("GET", "/api/supermetrics", tok, params={"pageSize": 1000, "page": n, "_no_links": "true"})
        got = (body.get("superMetrics") or []) if isinstance(body, dict) else []
        sms += got
        total = ((body.get("pageInfo") or {}).get("totalCount") if isinstance(body, dict) else None)
        n += 1
        if not got or total is None or len(sms) >= total or n > 20:
            break
    mine = [s for s in sms if str(s.get("name") or "").startswith(owner + " - ")]
    arm = {}
    for role, needle in ROLES:
        hit = next((s for s in mine if needle in str(s.get("name"))), None)
        arm[role] = {"present": bool(hit), "id": (hit or {}).get("id"),
                     "formulaLength": len(str((hit or {}).get("formula") or "")) or None}
    print(f"  CONTENT: {sum(1 for v in arm.values() if v['present'])} of {len(ROLES)} reachability metrics "
          f"found among your {len(mine)} owned super metrics")
    for role, v in arm.items():
        print(f"     {role:<12} {'present' if v['present'] else 'MISSING'}")

    # ---- 2: is it computing
    st, body = ops("GET", "/api/resources", tok,
                   params={"resourceKind": "ping_adapter_instance", "pageSize": 20, "_no_links": "true"})
    instances = (body.get("resourceList") or []) if isinstance(body, dict) else []
    computed, ages = {}, []
    inst = instances[0] if instances else None
    if inst:
        stats = latest(inst["identifier"], tok, now)
        by_id = {v["id"]: role for role, v in arm.items() if v.get("id")}
        for key, (value, age) in stats.items():
            m = re.match(r"Super Metric\|sm_(.+)$", key)
            if m and m.group(1) in by_id:
                computed[by_id[m.group(1)]] = {"value": value, "ageMinutes": age}
                ages.append(age)
        # The per-check delivery metric is computed on each check object, not on the instance, so its absence
        # here is the design rather than a gap. Only the four roll-ups should appear.
        rollups = [r for r in ("checks", "reachable", "unreachable", "sli") if arm[r]["present"]]
        print(f"\n  COMPUTING: {len(computed)} of the {len(rollups)} roll-up metrics carry a current value on "
              f"the adapter instance (the per-check delivery metric computes on each check, not here)")
        for role, v in computed.items():
            print(f"     {role:<12} {v['value']:<12} {v['ageMinutes']} minutes old")
        if ages and max(ages) - min(ages) < 1 and max(ages) > 60:
            print(f"     every reading is the same age and over an hour old, which is the signature of a "
                  f"stopped collector rather than a stopped fleet")

    # ---- 3: the denominator, and the shape of the failure
    tree, blocks = {}, collections.defaultdict(lambda: {"reachable": 0, "unreachable": 0})
    if inst:
        st, body = ops("GET", f"/api/resources/{inst['identifier']}/relationships/children", tok,
                       params={"_no_links": "true"})
        kids = (body.get("resourceList") or []) if isinstance(body, dict) else []
        kinds = collections.Counter((k.get("resourceKey") or {}).get("resourceKindKey") for k in kids)
        raw = {}
        for kind in ("ip_type", "fqdn_type"):
            st, b = ops("GET", "/api/resources", tok,
                        params={"resourceKind": kind, "pageSize": 1, "_no_links": "true"})
            raw[kind] = ((b.get("pageInfo") or {}).get("totalCount") if isinstance(b, dict) else None)
        losses = []
        labels, nextlabel = {}, iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        for k in kids:
            name = (k.get("resourceKey") or {}).get("name")
            kind = (k.get("resourceKey") or {}).get("resourceKindKey")
            stats = latest(k["identifier"], tok, now)
            loss = (stats.get("peak_packet_loss") or (None, None))[0]
            losses.append(loss)
            blk = block_of(name) if kind != "fqdn_type" else None
            # setdefault would evaluate next() on every call and exhaust the labels after ten checks, which
            # is what it did first. Only mint a label when the block is actually new.
            if blk is None:
                label = "a name check"
            else:
                if blk not in labels:
                    labels[blk] = f"block {next(nextlabel)}"
                label = labels[blk]
            blocks[label]["reachable" if (loss is not None and loss < 100) else "unreachable"] += 1
        tree = {"directChildren": len(kids), "byKind": dict(kinds), "rawObjects": raw,
                "foldedUnderAName": (raw.get("ip_type") or 0) + (raw.get("fqdn_type") or 0) - len(kids),
                "lossDistribution": dict(collections.Counter(losses)),
                "byBlock": {k: v for k, v in blocks.items()}}
        print(f"\n  DENOMINATOR: {len(kids)} direct children ({dict(kinds)}) against "
              f"{sum(v for v in raw.values() if v)} raw check objects; "
              f"{tree['foldedUnderAName']} fold under a name check")
        print(f"  SHAPE: packet loss distribution {tree['lossDistribution']}")
        for label, v in sorted(blocks.items()):
            print(f"     {label:<12} reachable {v['reachable']}, unreachable {v['unreachable']}")
        bad = [l for l, v in blocks.items() if v["unreachable"] and not v["reachable"]]
        if len(bad) == 1:
            print(f"     every unreachable check sits in {bad[0]} and every check elsewhere answers, so this "
                  f"is one cause to find rather than several failures")

    # ---- 4: the guest layer against the floor
    # Every VirtualMachine resource, read to the list's declared total. A resource an adapter reports as
    # NOT_EXISTING is a deleted machine's record, not a machine: it keeps its last values, a guest KPI of zero
    # among them. The floor is the hypervisor's power state, a property, beside the AGE of the uptime reading:
    # a powered-off machine keeps its last uptime, so a latest uptime above zero says nothing about now unless
    # the reading is current.
    vms, page = [], 0
    while True:
        st, body = ops("GET", "/api/resources", tok,
                       params={"resourceKind": "VirtualMachine", "pageSize": 1000, "page": page, "_no_links": "true"})
        got = (body.get("resourceList") or []) if isinstance(body, dict) else []
        vms += got
        total = ((body.get("pageInfo") or {}).get("totalCount") if isinstance(body, dict) else None)
        page += 1
        if not got or total is None or len(vms) >= total or page > 50:
            break
    gone = {v["identifier"] for v in vms if v.get("identifier") and "NOT_EXISTING" in
            {s.get("resourceState") for s in v.get("resourceStatusStates") or []}}
    ids = [v["identifier"] for v in vms if v.get("identifier")]
    guest = {}
    if ids:
        st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                       body={"resourceId": ids, "statKey": ["summary|availability_kpi", "sys|uptime_latest"]})
        per = collections.defaultdict(dict)
        nowms = now.timestamp() * 1000
        for v in ((body.get("values") or []) if isinstance(body, dict) else []):
            for s in (v.get("stat-list") or {}).get("stat", []):
                if s.get("data") and s.get("timestamps"):
                    per[v.get("resourceId")][s["statKey"]["key"]] = (s["data"][-1], (nowms - s["timestamps"][-1]) / 60000)
        st, body = ops("POST", "/api/resources/properties/latest/query", tok,
                       body={"resourceIds": ids, "propertyKeys": ["summary|runtime|powerState"]})
        power = {}
        for v in ((body.get("values") or []) if isinstance(body, dict) else []):
            for p in (v.get("property-contents") or {}).get("property-content") or []:
                if p.get("statKey") == "summary|runtime|powerState" and p.get("values"):
                    power[v["resourceId"]] = p["values"][-1]

        def kpi(r):
            return (per[r].get("summary|availability_kpi") or (None, None))[0]

        def uptime_current(r):
            u = per[r].get("sys|uptime_latest")
            return bool(u and u[0] and u[0] > 0 and u[1] <= FRESH_MINUTES)

        live = [r for r in ids if r not in gone]
        zero = [r for r in live if kpi(r) == 0]
        on = [r for r in zero if power.get(r) == "Powered On"]
        guest = {"resources": len(ids), "declaredTotal": total, "deletedMachineRecords": len(gone),
                 "deletedReadingKpiZero": sum(1 for r in gone if kpi(r) == 0),
                 "machines": len(live), "reporting": sum(1 for r in live if kpi(r) is not None),
                 "kpiHundred": sum(1 for r in live if kpi(r) == 100), "kpiZero": len(zero),
                 "kpiZeroPoweredOff": sum(1 for r in zero if power.get(r) == "Powered Off"),
                 "kpiZeroPoweredOnUptimeCurrent": sum(1 for r in on if uptime_current(r)),
                 "kpiZeroPoweredOnUptimeNotCurrent": sum(1 for r in on if not uptime_current(r)),
                 "kpiZeroOtherPowerState": sum(1 for r in zero if power.get(r) not in ("Powered On", "Powered Off")),
                 "kpiZeroPoweredOffKeepingAnUptime": sum(1 for r in zero if power.get(r) == "Powered Off"
                                                         and (per[r].get("sys|uptime_latest") or (0,))[0] > 0),
                 "kpiHundredButPoweredOff": sum(1 for r in live if kpi(r) == 100 and power.get(r) == "Powered Off"),
                 "freshMinutes": FRESH_MINUTES,
                 # What reading the latest uptime alone, deleted records included, would have said: the rule
                 # this script used before it read power state and existence.
                 "uptimeAloneWouldSay": {
                     "running": sum(1 for r in ids if kpi(r) == 0 and (per[r].get("sys|uptime_latest") or (0,))[0] > 0),
                     "stopped": sum(1 for r in ids if kpi(r) == 0 and (per[r].get("sys|uptime_latest") or (None,))[0] == 0),
                     "unmeasured": sum(1 for r in ids if kpi(r) == 0 and "sys|uptime_latest" not in per[r])}}
        print(f"\n  GUEST AGAINST THE FLOOR: {guest['resources']} machine records, {guest['deletedMachineRecords']} of them "
              f"for machines that no longer exist ({guest['deletedReadingKpiZero']} of those still read a KPI of zero)")
        print(f"     {guest['kpiZero']} of the {guest['machines']} machines that exist read a guest KPI of zero:")
        print(f"     {guest['kpiZeroPoweredOff']} are powered off: down, or off on purpose")
        print(f"     {guest['kpiZeroPoweredOnUptimeCurrent']} are powered on with a current uptime: running, the guest "
              f"layer blind (VMware Tools silent)")
        print(f"     {guest['kpiZeroPoweredOnUptimeNotCurrent']} are powered on without a current uptime reading: unknown")
        if guest["kpiZeroOtherPowerState"]:
            print(f"     {guest['kpiZeroOtherPowerState']} report another power state or none: unknown")
        if guest["kpiZeroPoweredOffKeepingAnUptime"]:
            print(f"     {guest['kpiZeroPoweredOffKeepingAnUptime']} of the powered-off machines still carry their last "
                  f"uptime above zero, which is why a latest uptime is not a running machine")
        w = guest["uptimeAloneWouldSay"]
        print(f"     the latest uptime alone, deleted records included, would have said {w['running']} running, "
              f"{w['stopped']} stopped and {w['unmeasured']} unmeasured")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "owner": owner,
               "content": arm, "computed": computed, "tree": tree, "guest": guest,
               "pingInstances": len(instances)}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    assert not IPV4.search(text), "an address reached the record"
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "promise.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote promise.json; checks are grouped by anonymised block and no address is named")


if __name__ == "__main__":
    main()
