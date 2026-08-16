"""wtpc/lib/_evidence — the shared read-only metric read for the estate evidence CLIs.

The evidence rollups (compliance_rollup, capacity_runway, estate_ledger, tier_rollup) are read-only CLI
surfaces for estate AGGREGATES that have no vROps object to bind a dashboard row to. They share one core
read — the LATEST value of a stat on a resource — so it lives here, and every rollup reads metrics the same way.
"""
from __future__ import annotations


def latest_stat(c, rid: str, statkey: str):
    """The latest value of `statkey` on resource `rid` (the first stat's last data point), or None. Uses the
    batch latest-query (POST /api/resources/stats/latest/query) with a single (resource, stat) — the read
    every evidence rollup does per cluster/host. Works for any stat: super-metrics (via sm_stat_key), native
    capacity analytics, or config properties."""
    r = c.post("/api/resources/stats/latest/query",
               json={"resourceId": [rid], "statKey": [statkey]}, params={"_no_links": "true"})
    for v in r.json().get("values", []):
        for s in v.get("stat-list", {}).get("stat", []):
            d = s.get("data") or []
            return d[-1] if d else None
    return None
