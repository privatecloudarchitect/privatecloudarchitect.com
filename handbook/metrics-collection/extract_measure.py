#!/usr/bin/env python3
"""extract_measure.py - your own extraction coefficients, from a few bounded reads.

Measures what an ELT pipeline needs to size itself: points, bytes, latency, bytes per point, and
points per second for (1) one VM and one statkey over 7 days at native 5-minute resolution,
(2) the same window as hourly AVG buckets (server-side roll-up), and optionally (3) a fan-out of
N VMs x 4 statkeys over 1 day. Resources with no data in a window are omitted from the response,
so the omitted count is reported as absence, not as an error. Calls run one at a time.

Usage:  python3 extract_measure.py [--vm <name>] [--vms N]
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 measured · 2 a read failed
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from opslib import _ctx, bearer
from pick import list_vms, pick

KEYS4 = ["cpu|usagemhz_average", "mem|active_average", "cpu|readyPct", "mem|consumed_average"]


def timed_query(tok, body):
    """POST /api/resources/stats/query, returning (points, stats, resources, bytes, seconds)."""
    host = os.environ["OPS_HOST"]
    req = urllib.request.Request(
        f"https://{host}/suite-api/api/resources/stats/query?_no_links=true",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json",
                 "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=300) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"FATAL: stats query -> HTTP {e.code}: {e.read()[:200]!r}")
    secs = time.monotonic() - t0
    parsed = json.loads(raw) if raw else {}
    values = parsed.get("values", [])
    stats = sum(len(v.get("stat-list", {}).get("stat", [])) for v in values)
    points = sum(len(s.get("timestamps", [])) for v in values for s in v.get("stat-list", {}).get("stat", []))
    return points, stats, len(values), len(raw), secs


def row(label, points, nbytes, secs, requested=None, returned=None):
    bpp = nbytes / points if points else 0
    pps = points / secs if secs else 0
    omitted = "" if requested is None else f"  omitted {requested - returned} of {requested} resources"
    print(f"  {label:44}{points:>10,}{nbytes:>12,}{secs:>8.2f}{bpp:>8.1f}{pps:>10,.0f}{omitted}")


def main():
    argv = sys.argv[1:]
    fan = int(argv[argv.index("--vms") + 1]) if "--vms" in argv else 0
    tok = bearer()
    rid, name, _ = pick(tok, argv)
    end = int(time.time() * 1000)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"EXTRACTION COEFFICIENTS - read {stamp}, sequential calls\n")
    print(f"  {'call':44}{'points':>10}{'bytes':>12}{'secs':>8}{'B/pt':>8}{'pts/s':>10}")
    print("  " + "-" * 92)
    d7 = 7 * 86400 * 1000
    p, s, r, b, t = timed_query(tok, {"resourceId": [rid], "statKey": [KEYS4[0]], "begin": end - d7, "end": end})
    row(f"1 VM x 1 key, 7 d, native 5-minute", p, b, t)
    p, s, r, b, t = timed_query(tok, {"resourceId": [rid], "statKey": [KEYS4[0]], "begin": end - d7, "end": end,
                                      "intervalType": "HOURS", "intervalQuantifier": 1, "rollUpType": "AVG"})
    row(f"1 VM x 1 key, 7 d, hourly AVG (server-side)", p, b, t)
    if fan:
        vms = [v[0] for v in list_vms(tok)][:fan]
        d1 = 86400 * 1000
        p, s, r, b, t = timed_query(tok, {"resourceId": vms, "statKey": KEYS4, "begin": end - d1, "end": end})
        row(f"{len(vms)} VMs x 4 keys, 1 d, native", p, b, t, len(vms), r)
        p, s, r, b, t = timed_query(tok, {"resourceId": vms, "statKey": KEYS4, "begin": end - d1, "end": end,
                                          "intervalType": "HOURS", "intervalQuantifier": 1, "rollUpType": "AVG"})
        row(f"{len(vms)} VMs x 4 keys, 1 d, hourly AVG", p, b, t, len(vms), r)
    print("  " + "-" * 92)
    print(f"\n  sample VM: {name}. Latency has a fixed floor per call; batch wide rather than loop deep."
          "\n  An omitted resource had no data in the window: reconcile it against inventory and collector"
          "\n  health, never land it as zero. These coefficients are inputs to your estimate, from your node.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
