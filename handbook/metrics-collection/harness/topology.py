#!/usr/bin/env python3
"""topology.py - the collection topology of one Operations instance, read-only: which collector holds each adapter,
whether each proxy persists data through a link failure, and whether any group gives a site a second proxy.

Reads three public endpoints and changes nothing:
  GET /api/collectors                    every collector: its type (a unified cloud proxy, or the node's own internal
                                         collector), state, last heartbeat, the data-persistence flag, its adapters
  GET /api/collectorgroups               every collector group: its members, and whether HA and load balancing are on
  GET /api/collectors/{id}/adapters      each collector's adapter instances, counted by adapter kind
Then it checks the instance against the documented pattern a regional design rests on:
  - every cloud proxy is up and has persistence on, so a link outage of under an hour is buffered, not lost;
  - no vCenter, NSX or vSAN adapter sits on the node's internal collector, so the node stays thin
    and a site's collection rides that site's proxy;
  - a proxy alone in its group has no failover; that is reported as information, because HA is a choice
    (a second proxy and a 10-minute failover), not a defect.

Usage:  python3 topology.py
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN_FILE, ...)
Exit:   0 the instance matches the pattern · 1 a proxy is down, persistence is off, or a vCenter, NSX or vSAN
        adapter is on the node
        · 4 a read was refused or came back short
"""

import collections
import sys
import time
from datetime import datetime, timezone

from opslib import bearer, ops

# adapter kinds that collect a site's own vCenter, NSX and vSAN; on the node's internal collector they pull site traffic
# through the node instead of the site's proxy. The platform's own health and management adapters run on every
# collector, the node's included, by design, so they are listed but never judged.
SITE_KINDS = {"VMWARE", "NSXTAdapter", "VirtualAndPhysicalSANAdapter"}


def read(path, tok, key):
    """One read, whole or stopped: a refused or empty answer is exit 4, never an empty topology."""
    st, body = ops("GET", path, tok)
    if st != 200 or not isinstance(body, dict) or key not in body:
        print(f"FATAL: GET {path} answered HTTP {st} without '{key}'")
        sys.exit(4)
    return body[key] or []


def kinds_on(cid, tok):
    """The adapter kinds a collector runs, counted. The instance list carries each adapter's kind in its resource key."""
    insts = read(f"/api/collectors/{cid}/adapters", tok, "adapterInstancesInfoDto")
    return collections.Counter(((a.get("resourceKey") or {}).get("adapterKindKey") or "?") for a in insts), len(insts)


def main():
    tok = bearer()
    now = time.time()
    print(f"COLLECTION TOPOLOGY - read {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n")
    collectors = read("/api/collectors", tok, "collector")
    groups = read("/api/collectorgroups", tok, "collectorGroups")
    member_of = collections.defaultdict(list)
    for g in groups:
        for cid in g.get("collectorId") or []:
            member_of[str(cid)].append(g)
    findings, notes = [], []
    print(f"  {'collector':28} {'type':20} {'state':6} {'persist':8} {'heartbeat':10} {'adapters':>8}  kinds")
    print("  " + "-" * 104)
    for c in sorted(collectors, key=lambda x: (x.get("local") is not True, x.get("name") or "")):
        cid = str(c.get("id"))
        kinds, n = kinds_on(cid, tok)
        if n != len(c.get("adapterInstanceIds") or []):
            print(f"FATAL: collector {c.get('name')} lists {len(c.get('adapterInstanceIds') or [])} adapters and "
                  f"answers {n}")
            sys.exit(4)
        age = (now - (c.get("lastHeartbeat") or 0) / 1000) if c.get("lastHeartbeat") else None
        internal = c.get("local") is True or c.get("type") == "INTERNAL"
        top = ", ".join(f"{k} {v}" for k, v in kinds.most_common(4)) + (" ..." if len(kinds) > 4 else "")
        print(f"  {(c.get('name') or '?')[:28]:28} {(c.get('type') or '?')[:20]:20} {(c.get('state') or '?')[:6]:6} "
              f"{'on' if c.get('dataPersistenceEnabled') else 'off':8} "
              f"{(f'{age:.0f} s ago' if age is not None else 'never'):10} {n:>8}  {top}")
        if internal:
            print(f"  {'':28} the node's own adapters: {', '.join(sorted(kinds))}")
            site = sorted(k for k in kinds if k in SITE_KINDS)
            if site:
                findings.append(f"site adapters on the node's internal collector: {', '.join(site)}")
            continue
        if c.get("state") != "UP":
            findings.append(f"proxy {c.get('name')} is {c.get('state')}")
        if not c.get("dataPersistenceEnabled"):
            findings.append(f"proxy {c.get('name')} has data persistence off: a link outage loses data at once")
        mine = member_of.get(cid, [])
        if not any(len(g.get("collectorId") or []) > 1 for g in mine):
            notes.append(f"proxy {c.get('name')} has no partner in a group: no failover (a choice, not a defect)")
    print()
    print(f"  {'collector group':32} {'members':>7}  {'HA':4} {'LB':4} system-defined")
    print("  " + "-" * 64)
    for g in sorted(groups, key=lambda x: x.get("name") or ""):
        print(f"  {(g.get('name') or '?')[:32]:32} {len(g.get('collectorId') or []):>7}  "
              f"{'on' if g.get('haEnabled') else 'off':4} {'on' if g.get('lbEnabled') else 'off':4} "
              f"{'yes' if g.get('systemDefined') else 'no'}")
    print()
    for n in notes:
        print(f"  note: {n}")
    for f in findings:
        print(f"  FINDING: {f}")
    if not findings:
        print("  every proxy is up with persistence on, and the node's own collector holds no vCenter, NSX or vSAN adapter:")
        print("  the documented per-site pattern. A link outage under an hour is buffered; past it, the gap is real.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
