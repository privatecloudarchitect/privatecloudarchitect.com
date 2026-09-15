#!/usr/bin/env python3
"""rtm_query.py - one read of the Real-Time Metrics query API, the sheet's third collection path.

Mints the service-scoped JWT the VCF services runtime requires (rtmlib.py), then against
https://$RTM_HOST/data-query-service:
  1. GET /api/v1/metadata           the metric names the service knows (a count);
  2. GET /api/v1/query              one instant PromQL query, scoped by sourceId, then
                                     count by (profile) for the true series count: one call
                                     returns at most 101 series and reports the cut in warnings, so a
                                     large object set is read one host at a time;
  3. GET /api/v1/query_range        the same metric at a 2-second step over 3 minutes, one call
                                     per acquisition profile it is served under. The served
                                     cadence is the spacing between value changes: 2 s for the
                                     ESX Top profile, 20 s for the 20-second profiles, 5 minutes
                                     for the 300-second set. A range vector (metric[3m]) returns
                                     the 20-second grid for every profile and hides the 2-second
                                     data, so it is printed only as the contrast.
sourceId is the vCenter instance UUID (VMEntityVCID in Operations); it is required and not
validated, so a wrong value returns a successful empty answer. The JWT lasted 35 minutes on the
build this was proven on; the script mints a fresh one every run and never prints it.

Usage:  python3 rtm_query.py --source-id <vcenter-instance-uuid> [--metric <name>]
Env:    opslib.py's variables plus RTM_HOST (the VCF instance services FQDN)
Exit:   0 series returned · 1 no series for that source · 2 a read failed
"""

import sys
import time
from datetime import datetime, timezone

from opslib import bearer
from rtmlib import rtm_get, service_jwt

DEFAULT_METRIC = "cpu.utilization.PCORE"   # served under the ESX Top 2-second and the ESXi 20-second profiles
SERIES_CEILING = 101                       # the service's limit range is 1 to 101; above it the answer is truncated
FINE_STEP = "2s"
WINDOW_S = 180


def result(res):
    return ((res or {}).get("data") or {}).get("result") or []


def change_spacing(values):
    """Timestamps at which the value changed, and the smallest gap between two changes."""
    changed = [float(values[i][0]) for i in range(1, len(values)) if values[i][1] != values[i - 1][1]]
    gaps = [b - a for a, b in zip(changed, changed[1:])]
    return len(changed), (min(gaps) if gaps else None)


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

    st, inst, secs = rtm_get("/api/v1/query", jwt, {"query": metric, "sourceId": source})
    if st != 200:
        sys.exit(f"FATAL: GET /api/v1/query -> HTTP {st}: {inst}")
    series = result(inst)
    print(f"\n  instant query {metric}: {len(series)} series returned ({secs:.2f} s)")
    if not series:
        print("\n  no series: check the sourceId (the vCenter instance UUID), that this vCenter is"
              "\n  collected by Real-Time Metrics on this VCF instance, and that the metric name is"
              "\n  in this source's metadata; all three failures return a successful empty answer.")
        return 1
    labels = series[0].get("metric", {})
    print(f"    labels: {', '.join(sorted(k for k in labels if k != '__name__'))}")
    print("    object identity is the MOID label (vm, host, cluster, datacenter); the vCenter half"
          "\n    is the sourceId you passed, so stamp every row with it.")

    st, cnt, secs = rtm_get("/api/v1/query", jwt, {"query": f"count by (profile) ({metric})", "sourceId": source})
    if st != 200:
        sys.exit(f"FATAL: count by (profile) -> HTTP {st}: {cnt}")
    counts = {r.get("metric", {}).get("profile", "?"): int(float(r["value"][1])) for r in result(cnt)}
    total = sum(counts.values())
    print(f"\n  count by (profile): {total} series in the store"
          + "".join(f"\n    {p}: {n}" for p, n in sorted(counts.items())))
    warnings = [w for w in ((inst or {}).get("warnings") or []) if "truncat" in w.lower()]
    if warnings or len(series) < total:
        print(f"    the instant query returned {len(series)} of {total} and warned '{warnings[0] if warnings else 'truncated'}':"
              f"\n    one call returns at most {SERIES_CEILING} series; read a large object set one host at a time"
              f"\n    (a label matcher such as {{host=\"host-123\"}}), and treat the warning as an error in a pipeline.")

    end = int(time.time())
    start = end - WINDOW_S
    profiles = sorted(counts) or [None]
    print(f"\n  cadence, {metric} at step {FINE_STEP} over {WINDOW_S // 60} minutes, first series per profile:")
    for prof in profiles:
        selector = f'{metric}{{profile="{prof}"}}' if prof else metric
        st, rng, secs = rtm_get("/api/v1/query_range", jwt,
                                {"query": selector, "sourceId": source, "start": start, "end": end, "step": FINE_STEP})
        if st != 200:
            sys.exit(f"FATAL: GET /api/v1/query_range -> HTTP {st}: {rng}")
        rows = result(rng)
        values = rows[0].get("values", []) if rows else []
        changes, spacing = change_spacing(values)
        verdict = (f"{spacing:.0f} s between changes: the served cadence" if spacing
                   else "no value change in the window: idle or flat, no cadence readable")
        print(f"    {prof or 'all profiles'}: {len(values)} points, {changes} value changes, {verdict} ({secs:.2f} s)")

    st, rv, secs = rtm_get("/api/v1/query", jwt, {"query": f"{metric}[{WINDOW_S // 60}m]", "sourceId": source})
    if st != 200:
        sys.exit(f"FATAL: range-vector query -> HTTP {st}: {rv}")
    rows = result(rv)
    if rows and rows[0].get("values"):
        ts = [float(v[0]) for v in rows[0]["values"]]
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
        print(f"\n  contrast, range vector {metric}[{WINDOW_S // 60}m]: {len(ts)} raw samples in the first series,"
              f" spacing {gaps[0]:.0f} to {gaps[-1]:.0f} s ({secs:.2f} s)" if gaps else "")
        print("    a range vector returns the 20-second grid for every profile; it cannot show the 2-second data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
