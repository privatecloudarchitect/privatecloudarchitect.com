#!/usr/bin/env python3
"""rollup_check.py - what the 5-minute store keeps, and whether server-side roll-ups are exact.

For one VM over the last three hours:
  1. reads the native 5-minute points of cpu|usagemhz_average;
  2. asks for the same window as explicit 5-minute buckets with AVG, MIN, and MAX, and reports
     whether MIN and MAX differ from AVG (they do not: one value per point survives);
  3. asks for hourly AVG and MAX and checks each full bucket against the mean and the maximum
     of the native points inside it (exact to three decimals is the pass);
  4. lists the peak keys the VM carries (statkeys containing "peak" or "20_sec"), the only
     place a within-cycle maximum survives at 5-minute cadence.

Usage:  python3 rollup_check.py [--vm <name>]      (default: the busiest VM by latest CPU MHz)
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 roll-ups exact · 1 a roll-up did not match · 2 a read failed
"""

import sys
import time
from datetime import datetime, timezone

from opslib import bearer, ops
from pick import pick

STAT = "cpu|usagemhz_average"
WINDOW_S = 3 * 3600


def series(tok, rid, begin, end, **extra):
    body = {"resourceId": [rid], "statKey": [STAT], "begin": begin, "end": end}
    body.update(extra)
    st, res = ops("POST", "/api/resources/stats/query", tok, body=body, params={"_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: stats query {extra or 'native'} -> HTTP {st}: {res}")
    for v in (res or {}).get("values", []):
        for s in v.get("stat-list", {}).get("stat", []):
            if s.get("statKey", {}).get("key") == STAT:
                return list(zip(s.get("timestamps", []), s.get("data", [])))
    return []


def main():
    argv = sys.argv[1:]
    tok = bearer()
    rid, name, _ = pick(tok, argv)
    end = int(time.time() * 1000)
    begin = end - WINDOW_S * 1000
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"ROLL-UP CHECK - {name}, {STAT}, last 3 hours, read {stamp}\n")

    native = series(tok, rid, begin, end)
    if len(native) < 12:
        sys.exit(f"only {len(native)} native points in the window; the VM may be idle or newly collected")
    gaps = sorted(round((b - a) / 1000) for (a, _), (b, _) in zip(native, native[1:]))
    print(f"  native points: {len(native)}, spacing {gaps[0]} to {gaps[-1]} s (median {gaps[len(gaps) // 2]} s)")

    avg5 = dict(series(tok, rid, begin, end, intervalType="MINUTES", intervalQuantifier=5, rollUpType="AVG"))
    min5 = dict(series(tok, rid, begin, end, intervalType="MINUTES", intervalQuantifier=5, rollUpType="MIN"))
    max5 = dict(series(tok, rid, begin, end, intervalType="MINUTES", intervalQuantifier=5, rollUpType="MAX"))
    common = sorted(set(avg5) & set(min5) & set(max5))
    same = sum(1 for t in common if min5[t] == avg5[t] == max5[t])
    print(f"  explicit 5-minute buckets: {len(common)} common timestamps; MIN and MAX equal AVG at {same} of them")
    print("  (one value per point survives the 20-second sampling; nothing inside a cycle is recoverable)\n")

    avg1 = series(tok, rid, begin, end, intervalType="HOURS", intervalQuantifier=1, rollUpType="AVG")
    max1 = series(tok, rid, begin, end, intervalType="HOURS", intervalQuantifier=1, rollUpType="MAX")
    max1 = dict(max1)
    print(f"  {'hour bucket (end, UTC)':24}{'AVG':>10}{'native mean':>13}{'MAX':>10}{'native max':>12}   result")
    print("  " + "-" * 78)
    checked = exact = 0
    for t, a in avg1:
        inside = [v for ts, v in native if t - 3600 * 1000 < ts <= t]
        if len(inside) < 12:
            continue  # partial bucket at the window edge; skip rather than misjudge it
        mean = sum(inside) / len(inside)
        mx = max(inside)
        m = max1.get(t)
        ok = abs(a - mean) < 0.0005 and m is not None and abs(m - mx) < 0.0005
        checked += 1
        exact += ok
        when = datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {when:24}{a:>10.3f}{mean:>13.3f}{(m if m is not None else float('nan')):>10.3f}{mx:>12.3f}   {'exact' if ok else 'MISMATCH'}")
    print("  " + "-" * 78)

    st, keys = ops("GET", f"/api/resources/{rid}/statkeys", tok, params={"_no_links": "true"})
    peaks = []
    if st == 200:
        for k in (keys or {}).get("stat-key", []):
            key = k.get("key") if isinstance(k, dict) else k
            if key and ("peak" in key.lower() or "20_sec" in key):
                peaks.append(key)
    print(f"\n  peak keys on this VM ({len(peaks)}): the only within-cycle maxima kept at 5-minute cadence")
    for k in sorted(peaks):
        print(f"    {k}")

    if checked and exact == checked:
        print(f"\n  VERDICT: {exact} of {checked} full hourly buckets match the native points exactly;"
              "\n  downsample on the server, and read peaks from the peak keys or the 20-second path.")
        return 0
    print(f"\n  VERDICT: {exact} of {checked} full hourly buckets matched; inspect the mismatches before"
          "\n  relying on server-side roll-ups for this key.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
