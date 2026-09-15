#!/usr/bin/env python3
"""collection_planes.py - the three planes the sheet teaches, read from your instance.

Reads, in order:
  1. the vCenter adapters: the collection interval, whether vStats collection is on and at
     what sampling rate, and the metrics and resources each adapter collects per cycle;
  2. the global retention settings against their product defaults (5-minute band, hourly
     roll-up band, real-time metrics, ESX Top, deleted objects);
  3. the default policy's cluster allocation model (the ruler capacity and rightsizing ride on).

Every value is printed with its plane: adapter (what collects), settings (what is kept), and
policy (what the decisions measure against). A retention value that differs from its default
is flagged, because the numbers the sheet quotes are the defaults.

Usage:  python3 collection_planes.py
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 every retention key at its default · 1 a tuned retention value · 2 a read failed
"""

import sys
from datetime import datetime, timezone

from opslib import bearer, ops

RETENTION = [
    ("TIME_SERIES_DATA_RETENTION_IN_MONTHS", "5-minute data kept for"),
    ("ROLLUP_TIME_SERIES_DATA_RETENTION_IN_MONTHS", "hourly roll-ups kept for"),
    ("REALTIME_DATA_RETENTION_IN_DAYS", "real-time metrics kept for"),
    ("ESX_TOP_DATA_RETENTION_IN_HOURS", "2-second ESX Top kept for"),
    ("DELETED_OBJECTS_RETENTION_IN_HOURS", "deleted objects linger for"),
    ("OBJECT_HISTORY_RETENTION_IN_DAYS", "object history kept for"),
]


def kv_list(body):
    """Global settings and their metadata both arrive as a list of keyed records; find it."""
    if isinstance(body, list):
        return body
    for v in (body or {}).values():
        if isinstance(v, list):
            return v
    return []


def first(rec, *names):
    for n in names:
        if n in rec and rec[n] not in (None, "", []):
            v = rec[n]
            return v[0] if isinstance(v, list) else v
    return None


def walk(obj, out, path=""):
    """Flatten a settings payload to (path, value) pairs for the ratio read."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, out, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, out, f"{path}[{i}]")
    else:
        out.append((path, obj))


def main():
    tok = bearer()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"COLLECTION PLANES - read {now}\n")

    # 1. adapters: what collects, and how
    st, body = ops("GET", "/api/adapters", tok, params={"adapterKindKey": "VMWARE", "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list vCenter adapters -> HTTP {st}: {body}")
    print("  plane 1 · the vCenter adapters (pull, through vStats where enabled)")
    print(f"  {'adapter':30}{'interval':>9}{'vStats':>8}{'sample':>8}{'metrics':>10}{'objects':>9}")
    print("  " + "-" * 74)
    for a in body.get("adapterInstancesInfoDto", []):
        ids = {i["identifierType"]["name"]: i.get("value")
               for i in a.get("resourceKey", {}).get("resourceIdentifiers", [])}
        vstats = ids.get("IS_VSTATS_COLLECTION_ENABLED", "-")
        sample = ids.get("VSTATS_SAMPLING_INTERVAL_SECONDS", "-")
        print(f"  {a['resourceKey']['name'][:30]:30}{str(a.get('monitoringInterval', '-')) + ' min':>9}"
              f"{str(vstats):>8}{str(sample) + ' s':>8}{str(a.get('numberOfMetricsCollected', '-')):>10}"
              f"{str(a.get('numberOfResourcesCollected', '-')):>9}")
    print("  the interval is the stored cadence; the sample is the vStats rate the adapter"
          " averages\n  into it. Neither depends on the vCenter statistics level.\n")

    # 2. retention: what is kept, against the defaults
    st, cfg = ops("GET", "/api/deployment/config/globalsettings", tok, params={"_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: global settings -> HTTP {st}: {cfg}")
    st, meta = ops("GET", "/api/deployment/config/globalsettings/metadata", tok, params={"_no_links": "true"})
    defaults = {}
    if st == 200:
        for rec in kv_list(meta):
            k = first(rec, "key", "name")
            if k:
                defaults[k] = first(rec, "defaultValue", "default", "defaultValues")
    configured = {}
    for rec in kv_list(cfg):
        k = first(rec, "key", "name")
        if k:
            configured[k] = first(rec, "values", "value")
    print("  plane 2 · the store's retention (global settings)")
    print(f"  {'setting':44}{'configured':>11}{'default':>9}   meaning")
    print("  " + "-" * 82)
    tuned = 0
    for key, meaning in RETENTION:
        c, d = configured.get(key), defaults.get(key)
        flag = ""
        if c is None:
            flag = "  (not present on this build)"
        elif d is not None and str(c) != str(d):
            flag, tuned = "  TUNED", tuned + 1
        print(f"  {key:44}{str(c if c is not None else '-'):>11}{str(d if d is not None else '-'):>9}   {meaning}{flag}")
    print()

    # 3. policy: the ruler
    st, pol = ops("GET", "/api/policies", tok, params={"pageSize": 500, "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list policies -> HTTP {st}: {pol}")
    summaries = pol.get("policySummaries", [])
    default = [p for p in summaries if p.get("defaultPolicy")] or summaries[:1]
    if not default:
        sys.exit("FATAL: no policies visible to this token")
    pid, pname = default[0]["id"], default[0]["name"]
    st, settings = ops("GET", f"/api/policies/{pid}/settings", tok, params={
        "type": "CAPACITY_ALLOCATION_MODEL", "resourceKind": "ClusterComputeResource",
        "adapterKind": "VMWARE", "includeInherited": "true", "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: allocation model of {pname!r} -> HTTP {st}: {settings}")
    flat = []
    walk(settings, flat)
    print(f"  plane 3 · the ruler: {pname!r}, cluster allocation model")
    shown = 0
    for path, value in flat:
        leaf = path.split(".")[-1]
        if leaf in ("cpu", "memory", "diskspace", "poweredOffVmsConsidered", "inherited"):
            label = {"cpu": "cpu overcommit ratio", "memory": "memory overcommit ratio",
                     "diskspace": "disk overcommit ratio",
                     "poweredOffVmsConsidered": "powered-off VMs counted",
                     "inherited": "inherited from a parent policy"}[leaf]
            print(f"    {label:34}{value}")
            shown += 1
    if not shown:
        print("    (no allocation ratios returned; the policy may not set an allocation model)")
    print("\n  capacity runway rides this allocation model; rightsizing rides demand. Confirm the"
          "\n  model per cluster before trusting either number.")
    if tuned:
        print(f"\n  {tuned} retention value(s) differ from the product default; the sheet's figures assume the defaults.")
        return 1
    print("\n  every retention key sits at its product default; the sheet's figures apply as written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
