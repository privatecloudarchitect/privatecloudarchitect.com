#!/usr/bin/env python3
"""rtm_query.py - one read of the Real-Time Metrics query API, the sheet's third collection path.

Mints the service-scoped JWT the VCF services runtime requires (rtmlib.py), then against
https://$RTM_HOST/data-query-service:
  1. GET /api/v1/metadata           the metric names the service knows (a count);
  2. GET /api/v1/query              one instant PromQL query, scoped by sourceId;
  3. GET /api/v1/query               the same metric as a range vector, metric[10m], to read the
                                     raw sample spacing (a step-based range query would repeat
                                     the last value at every step and hide the cadence).
sourceId is the vCenter instance UUID (VMEntityVCID in Operations); it is required and not
validated, so a wrong value returns a successful empty answer. The JWT lasted 35 minutes on the
build this was proven on; the script mints a fresh one every run and never prints it.

Usage:  python3 rtm_query.py --source-id <vcenter-instance-uuid> [--metric <name>]
Env:    opslib.py's variables plus RTM_HOST (the VCF instance services FQDN)
Exit:   0 series returned · 1 no series for that source · 2 a read failed
"""

import sys
from datetime import datetime, timezone

from opslib import bearer
from rtmlib import rtm_get, service_jwt

DEFAULT_METRIC = "cpu.capacity.contention.HOST"


def main():
    argv = sys.argv[1:]
    if "--source-id" not in argv:
        sys.exit("usage: rtm_query.py --source-id <vcenter-instance-uuid> [--metric <name>]")
    source = argv[argv.index("--source-id") + 1]
    metric = argv[argv.index("--metric") + 1] if "--metric" in argv else DEFAULT_METRIC
    jwt = service_jwt(bearer())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"REAL-TIME METRICS QUERY - read {stamp}, service JWT minted for this run (35-minute lifetime)\n")

    st, meta, secs = rtm_get("/api/v1/metadata", jwt, {"limit": 10000, "sourceId": source})
    if st != 200:
        sys.exit(f"FATAL: GET /api/v1/metadata -> HTTP {st}: {meta}")
    names = sorted((meta or {}).get("data", {}).keys())
    print(f"  metadata: {len(names)} metric names collected for this source ({secs:.2f} s)")
    if names:
        print(f"    e.g. {', '.join(names[:5])}")

    st, res, secs = rtm_get("/api/v1/query", jwt, {"query": metric, "sourceId": source})
    if st != 200:
        sys.exit(f"FATAL: GET /api/v1/query -> HTTP {st}: {res}")
    series = (res or {}).get("data", {}).get("result", [])
    print(f"\n  instant query {metric}: {len(series)} series ({secs:.2f} s)")
    if series:
        labels = series[0].get("metric", {})
        print(f"    labels: {', '.join(sorted(k for k in labels if k != '__name__'))}")
        print("    object identity is the MOID label (vm, host, cluster, datacenter); the vCenter half"
              "\n    is the sourceId you passed, so stamp every row with it.")

    st, res, secs = rtm_get("/api/v1/query", jwt, {"query": f"{metric}[10m]", "sourceId": source})
    if st != 200:
        sys.exit(f"FATAL: range-vector query -> HTTP {st}: {res}")
    rows = (res or {}).get("data", {}).get("result", [])
    if rows and rows[0].get("values"):
        ts = [float(v[0]) for v in rows[0]["values"]]
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
        print(f"\n  range vector {metric}[10m]: {len(rows)} series, {len(ts)} raw samples in the first;"
              f" spacing {gaps[0]:.0f} to {gaps[-1]:.0f} s ({secs:.2f} s)" if gaps else "")
        print("    the served grid; a step-based query_range would carry values forward and hide it.")
    if not series:
        print("\n  no series: check the sourceId (the vCenter instance UUID) and that this vCenter is"
              "\n  collected by Real-Time Metrics on this VCF instance.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
