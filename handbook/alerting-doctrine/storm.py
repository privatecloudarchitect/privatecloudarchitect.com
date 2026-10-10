#!/usr/bin/env python3
"""storm.py: what your VCF Operations instance raised, out of the box, when a host failed or went away.

When a host fails, does every VM on it raise an alert of its own? And when a cluster goes, does every host? A list of
definitions cannot answer that; the alert history can. This reads it, on a running instance:

  1. HOST INCIDENTS. Every alert of the two shipped host-availability definitions the instance still holds, grouped
     into events: alerts that start within five minutes of an event's first alert belong to that event;
  2. AROUND EACH EVENT. Every alert that started from 15 minutes before the event to 90 minutes after, by object kind
     and definition; the ones on the VMs under the event's hosts now, and on their clusters. A VM alert whose name
     could say the VM is down is counted on its own, because that is the alert a cascade would be made of;
  3. THE VOCABULARY. The VirtualMachine definitions whose names could say a VM is down, and how often each has raised
     on this instance;
  4. CONTROL STATES. Every alert the instance holds, by control state. SUPPRESSED is the state a suppression leaves.

A window counts every alert that started in it, on any object, so it is an upper bound on what the event raised: an
alert in the window was not necessarily caused by the event. The alerts on the VMs under the event's hosts are the
closer reading, with one limit: a VM that moved since is counted under its host now.

Read-only throughout. Hosts, clusters and VMs are counted, never named; definitions appear under the product's names.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_REALM=CUSTOMER                       # the broker realm, usually this
  export OPS_API_TOKEN=<api-token>                # minted in the operations console
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 storm.py                                # writes storm.json
"""

import collections
import json
import os
import re
import time

from opslib import bearer, ops

HOST_DEFS = ("Host has lost connection to vCenter Server",
             "vSphere High Availability (HA) has detected a possible host failure")
DOWN = re.compile(r"power|down|unavailab|not respond|disconnect|heartbeat|orphan|inaccessible|unreachable|"
                  r"availability|crash|fail", re.I)
KINDS = ("HostSystem", "TransportNode", "ClusterComputeResource", "VirtualMachine")
BEFORE_MS, AFTER_MS, EVENT_MS = 15 * 60000, 90 * 60000, 5 * 60000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
REPORT = []


def say(line=""):
    print(line)
    REPORT.extend(str(line).split("\n"))


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000)) if ms else None


def main():
    tok = bearer()
    out_dir = os.environ.get("OUT_DIR", ".")
    say("storm.py: what this instance raised when a host failed or went away\n")

    alerts, page = [], 0
    while True:
        st, body = ops("POST", "/api/alerts/query", tok, body={"activeOnly": False},
                       params={"page": page, "pageSize": 5000})
        batch = (body or {}).get("alerts") or [] if st == 200 else []
        alerts += batch
        if len(batch) < 5000 or page > 40:
            break
        page += 1
    assert alerts, "the alert query returned nothing; check the token's rights before reading an empty history"
    kind_of = {}

    def kind(rid):
        if rid not in kind_of:
            st, r = ops("GET", f"/api/resources/{rid}", tok)
            kind_of[rid] = ((r or {}).get("resourceKey") or {}).get("resourceKindKey", "gone") if st == 200 else "gone"
        return kind_of[rid]

    def related(rid, which, want):
        st, r = ops("GET", f"/api/resources/{rid}/relationships/{which}", tok, params={"pageSize": 1000})
        return {x["identifier"] for x in (r or {}).get("resourceList") or []
                if x["resourceKey"]["resourceKindKey"] == want}

    start = lambda a: int(a["startTimeUTC"])  # noqa: E731
    incidents = sorted((a for a in alerts if a.get("alertDefinitionName") in HOST_DEFS), key=start)
    events = []
    for a in incidents:
        if events and start(a) - events[-1]["t"] <= EVENT_MS:
            events[-1]["alerts"].append(a)
        else:
            events.append({"t": start(a), "alerts": [a]})

    rows = []
    say(f"  1. HOST INCIDENTS: {len(incidents)} alert(s) of the shipped host-availability definitions, in "
        f"{len(events)} event(s); the history reaches back to {iso(min(start(a) for a in alerts))[:10]}")
    for n, ev in enumerate(events, start=1):
        t = ev["t"]
        hosts = sorted({a["resourceId"] for a in ev["alerts"] if kind(a["resourceId"]) == "HostSystem"})
        vms = set().union(*[related(h, "children", "VirtualMachine") for h in hosts]) if hosts else set()
        clusters = set().union(*[related(h, "parents", "ClusterComputeResource") for h in hosts]) if hosts else set()
        win = [x for x in alerts if t - BEFORE_MS <= start(x) <= t + AFTER_MS]
        by_kind = {k: [x for x in win if kind(x["resourceId"]) == k] for k in KINDS}
        vm_down = [x for x in by_kind["VirtualMachine"] if DOWN.search(x.get("alertDefinitionName") or "")]
        under = [x for x in win if x["resourceId"] in vms]
        row = {"event": n, "start": iso(t), "hosts": len(hosts), "clusters": len(clusters),
               "spreadSeconds": (max(start(a) for a in ev["alerts"]) - t) // 1000,
               "hostDefinitions": dict(collections.Counter(a["alertDefinitionName"] for a in ev["alerts"])),
               "longestHostAlertMinutes": max(((int(a["cancelTimeUTC"]) if a.get("cancelTimeUTC") else int(time.time() * 1000))
                                               - start(a)) // 60000 for a in ev["alerts"]),
               "window": {k: {"alerts": len(v), "objects": len({x["resourceId"] for x in v}),
                              "definitions": dict(collections.Counter(x["alertDefinitionName"] for x in v))}
                          for k, v in by_kind.items()},
               "windowOtherKinds": sum(1 for x in win if kind(x["resourceId"]) not in KINDS),
               "vmAlertsThatCouldSayDown": len(vm_down),
               "vmsUnderItsHostsNow": len(vms),
               "onThoseVms": dict(collections.Counter(x["alertDefinitionName"] for x in under)),
               "onItsClusters": dict(collections.Counter(x["alertDefinitionName"] for x in win
                                                         if x["resourceId"] in clusters))}
        rows.append(row)
        w = row["window"]
        say(f"     event {n}, {row['start']}: {len(hosts)} host(s) in {len(clusters)} cluster(s); in the window, host {w['HostSystem']['alerts']} on "
            f"{w['HostSystem']['objects']}, transport node {w['TransportNode']['alerts']}, cluster "
            f"{w['ClusterComputeResource']['alerts']}, VM {w['VirtualMachine']['alerts']} on "
            f"{w['VirtualMachine']['objects']} ({len(vm_down)} that could say down); on the {len(vms)} VMs under its "
            f"hosts now, {sum(row['onThoseVms'].values())}")

    st, body = ops("GET", "/api/alertdefinitions", tok, params={"page": 0, "pageSize": 5000, "_no_links": "true"})
    defs = (body or {}).get("alertDefinitions") or []
    ever = collections.Counter(a.get("alertDefinitionId") for a in alerts)
    vm_defs = [x for x in defs if x.get("resourceKindKey") == "VirtualMachine"]
    down = [{"name": x["name"], "raised": ever.get(x["id"], 0)} for x in sorted(vm_defs, key=lambda x: x["name"])
            if DOWN.search(x["name"])]
    say(f"\n  2. THE VOCABULARY: {len(down)} of {len(vm_defs)} VirtualMachine definitions have a name that could say a "
        f"VM is down; together they have raised {sum(d['raised'] for d in down)} time(s) here")
    for d in down:
        say(f"        {d['raised']:>4}  {d['name']}")
    control = dict(collections.Counter(a.get("controlState") for a in alerts))
    say(f"\n  3. CONTROL STATES: {control} across the {len(alerts)} alert(s) held")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "alertsHeld": len(alerts), "oldestAlertStart": iso(min(start(a) for a in alerts)),
               "byStatus": dict(collections.Counter(a.get("status") for a in alerts)),
               "byControlState": control,
               "hostDefinitions": list(HOST_DEFS),
               "windowMinutes": {"before": BEFORE_MS // 60000, "after": AFTER_MS // 60000,
                                 "eventGrouping": EVENT_MS // 60000},
               "events": rows,
               "vmVocabulary": {"definitions": len(vm_defs), "couldSayDown": down},
               "definitionsTotal": len(defs),
               "report": REPORT}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "storm.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote storm.json ({len(events)} event(s)); hosts, clusters and VMs are counts, never names")


if __name__ == "__main__":
    main()
