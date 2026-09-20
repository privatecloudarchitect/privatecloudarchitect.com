#!/usr/bin/env python3
"""candidacy.py: run the memory-tiering lens against your own hosts, read-only.

The chapter teaches a gate and a trigger. This runs both against every host the Operations instance
collects, and reports four things the verdict alone does not tell you:

  1. WHERE EACH HOST LANDS. Active as a percent of the DRAM tier against the candidacy gate, and
     consumed as a percent of the DRAM tier against the activation trigger. Two columns, two
     questions, as the chapter insists;
  2. WHAT THE WRONG DENOMINATOR WOULD HAVE COST. The same candidacy percentage recomputed against
     `mem|totalCapacity_average`, per host, with the signed error. The error does not have one sign:
     on a host with a tier configured the total counts the tier and understates; on a host without
     one the total is usable memory net of hypervisor overhead and overstates;
  3. WHICH HOSTS ACTUALLY HAVE A TIER, and whether anything has ever moved into it. A configured
     tier and a used tier are different facts and the metric surface reports them separately;
  4. WHETHER THE 1:1 DEFAULT HOLDS. The uplift a 1:1 ratio would give you, against the tier size
     the host actually reports. Where those disagree, every number derived from the assumption
     inherits the error.

DETECTING A TIER. `mem:NVMe|memory_tier_total_capacity` is the wrong key for this: it is present on
every host and reads zero where there is no tier, so its presence proves nothing. The key that
discriminates is `mem:NVMe|memory_tier_size`, and the cleanest detector of all is the key set, which
a configured tier grows by nine (a tier size, a tier usage, and read/write latency and bandwidth on
both sides of the boundary).

Read-only throughout: resource lists, stat keys, and stat values. It writes nothing to the instance.

Run:
  export OPS_HOST=... OPS_BROKER_HOST=... OPS_API_TOKEN=...
  export OPS_TLS_VERIFY=false                 # only on a self-signed lab CA
  python3 candidacy.py                        # writes candidacy.json beside this file
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from opslib import bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

GATE = float(os.environ.get("MEMTIER_GATE", "50"))       # active pct of DRAM: the candidacy gate
TRIGGER = float(os.environ.get("MEMTIER_TRIGGER", "80"))  # consumed pct of DRAM: tiering begins

ACTIVE = "mem|active_average"
CONSUMED = "mem|consumed_average"
DRAM_CAP = "mem:DRAM|memory_tier_total_capacity"
NVME_CAP = "mem:NVMe|memory_tier_total_capacity"
NVME_SIZE = "mem:NVMe|memory_tier_size"
NVME_USED = "mem:NVMe|tier.usage"
TOTAL_CAP = "mem|totalCapacity_average"
SIGNALS = [ACTIVE, CONSUMED, DRAM_CAP, NVME_CAP, NVME_SIZE, NVME_USED, TOTAL_CAP,
           "mem|granted_average", "mem:DRAM|tier.usage"]

# The counters that only exist on a host with a tier configured. Every one of them reads on the
# NVMe side of the boundary, which is what makes them a fair test of whether the tier carries load.
NVME_COUNTERS = [NVME_USED, "mem:NVMe|latency.read_latest", "mem:NVMe|latency.write_latest",
                 "mem:NVMe|bandwidth.read_latest", "mem:NVMe|bandwidth.write_latest"]
DRAM_COUNTERS = ["mem:DRAM|latency.read_latest", "mem:DRAM|bandwidth.read_latest"]


def latest(tok, ids, keys):
    """{resourceId: {statKey: newest value}} for a batch of resources."""
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   {"resourceId": ids, "statKey": keys})
    if st != 200:
        raise SystemExit(f"stat query returned HTTP {st}")
    out = {}
    for v in (body or {}).get("values") or []:
        d = {}
        for s in v.get("stat-list", {}).get("stat", []):
            k, data = s.get("statKey", {}).get("key"), (s.get("data") or [])
            if k and data:
                d[k] = data[-1]
        out[v.get("resourceId")] = d
    return out


def statkeys(tok, rid):
    """The set of stat keys the instance collects for one resource. Note the container is
    `stat-key`, hyphenated: a reader who guesses `resourceStatKey` gets an empty set and a clean
    HTTP 200, which reads as a host with no metrics rather than as a wrong key."""
    st, body = ops("GET", f"/api/resources/{rid}/statkeys", tok, params={"_no_links": "true"})
    if st != 200:
        return set()
    return {k["key"] for k in ((body or {}).get("stat-key") or [])}


def history(tok, ids, keys, days=14):
    """Daily maxima over a window, so a zero is a sustained zero rather than one unlucky sample."""
    end = int(time.time() * 1000)
    st, body = ops("POST", "/api/resources/stats/query", tok,
                   {"resourceId": ids, "statKey": keys, "begin": end - days * 86400 * 1000,
                    "end": end, "rollUpType": "MAX", "intervalType": "DAYS",
                    "intervalQuantifier": 1})
    if st != 200:
        return {}
    out = {}
    for v in (body or {}).get("values") or []:
        for s in v.get("stat-list", {}).get("stat", []):
            data = s.get("data") or []
            if data:
                out.setdefault(v["resourceId"], {})[s["statKey"]["key"]] = {
                    "samples": len(data), "max": max(data), "min": min(data)}
    return out


def main():
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    tok = bearer()
    print("candidacy.py: the memory-tiering lens, run against your own hosts\n")

    st, body = ops("GET", "/api/resources", tok,
                   params={"resourceKind": "HostSystem", "pageSize": 1000, "_no_links": "true"})
    if st != 200:
        raise SystemExit(f"host list returned HTTP {st}")
    hosts = [h for h in ((body or {}).get("resourceList") or []) if h.get("identifier")]
    ids = [h["identifier"] for h in hosts]
    print(f"  hosts collected: {len(ids)}")
    if not ids:
        raise SystemExit("no HostSystem resources; nothing to measure")

    vals = latest(tok, ids, SIGNALS)

    rows = []
    for n, rid in enumerate(sorted(ids, key=lambda r: -(vals.get(r, {}).get(CONSUMED) or 0)), 1):
        d = vals.get(rid, {})
        a, con, dram, tot = d.get(ACTIVE), d.get(CONSUMED), d.get(DRAM_CAP), d.get(TOTAL_CAP)
        if a is None or con is None or not dram:
            print(f"  host {n}: skipped, one of active/consumed/DRAM-capacity did not read")
            continue
        tier_size = d.get(NVME_SIZE) or 0
        row = {"host": n,
               "activePctOfDram": round(100 * a / dram, 1),
               "consumedPctOfDram": round(100 * con / dram, 1),
               "candidate": (100 * a / dram) < GATE,
               "pastTrigger": (100 * con / dram) >= TRIGGER,
               "coldDramGiB": round((con - a) / 1048576, 1),
               "dramGiB": round(dram / 1048576, 1),
               "tierConfigured": bool(tier_size),
               "tierGiB": round(tier_size / 1048576, 1) if tier_size else 0,
               # The NVMe capacity key, recorded precisely because it is NOT a tier detector.
               "nvmeCapacityKeyReads": d.get(NVME_CAP)}
        if tot:
            wrong = 100 * a / tot
            row["activePctOfTotal"] = round(wrong, 1)
            row["denominatorErrorPct"] = round((wrong - 100 * a / dram) / (100 * a / dram) * 100, 1)
        if tier_size:
            # The 1:1 default, measured rather than assumed.
            row["upliftIfOneToOneGiB"] = round(dram / 1048576, 1)
            row["ratioDramToTier"] = round(tier_size / dram, 3)
        rows.append(row)

    cand = [r for r in rows if r["candidate"]]
    past = [r for r in rows if r["pastTrigger"]]
    tiered_rows = [r for r in rows if r["tierConfigured"]]
    print(f"\n  CANDIDACY: {len(cand)} of {len(rows)} host(s) sit under the {GATE:.0f} percent gate")
    print(f"  READINESS: {len(past)} of {len(rows)} host(s) are at or past the {TRIGGER:.0f} percent trigger")
    print(f"  TIER:      {len(tiered_rows)} of {len(rows)} host(s) have an NVMe tier configured")
    for r in rows:
        mark = "TIER" if r["tierConfigured"] else "    "
        print(f"    host {r['host']:>2} {mark}  active {r['activePctOfDram']:>5.1f}%  "
              f"consumed {r['consumedPctOfDram']:>5.1f}%  cold {r['coldDramGiB']:>7.1f} GiB"
              + (f"  tier {r['tierGiB']:.1f} GiB (ratio 1:{r['ratioDramToTier']})" if r["tierConfigured"] else ""))

    # ---- the denominator, in both directions
    errs = [r for r in rows if "denominatorErrorPct" in r]
    t_err = [r["denominatorErrorPct"] for r in errs if r["tierConfigured"]]
    u_err = [r["denominatorErrorPct"] for r in errs if not r["tierConfigured"]]
    denom = {"tieredHosts": t_err, "untieredHosts": u_err,
             "changesSign": bool(t_err and u_err and min(u_err) > 0 > max(t_err))}
    print(f"\n  DENOMINATOR: recomputing candidacy against total capacity instead of the DRAM tier")
    if t_err:
        print(f"    on a host WITH a tier:    {min(t_err):+.1f}% to {max(t_err):+.1f}%  (the total counts the tier: understates)")
    if u_err:
        print(f"    on a host WITHOUT a tier: {min(u_err):+.1f}% to {max(u_err):+.1f}%  (the total is net of overhead: overstates)")
    if denom["changesSign"]:
        print(f"    the error CHANGES SIGN at activation, so a single correction factor cannot fix it")

    # ---- is a configured tier a used tier?
    tier_ids = [rid for rid in ids
                if (vals.get(rid, {}).get(NVME_SIZE) or 0)]
    usage = {}
    if tier_ids:
        live = latest(tok, tier_ids, NVME_COUNTERS + DRAM_COUNTERS)
        hist = history(tok, tier_ids, [NVME_USED])
        zero_now = sum(1 for rid in tier_ids
                       if all(not (live.get(rid, {}).get(k) or 0) for k in NVME_COUNTERS))
        dram_live = sum(1 for rid in tier_ids
                        if any((live.get(rid, {}).get(k) or 0) for k in DRAM_COUNTERS))
        samples = [h.get(NVME_USED, {}).get("samples", 0) for h in hist.values()]
        maxima = [h.get(NVME_USED, {}).get("max", 0) for h in hist.values()]
        usage = {"tieredHosts": len(tier_ids), "everyNvmeCounterZeroNow": zero_now,
                 "dramSideCarryingTraffic": dram_live, "nvmeCounters": len(NVME_COUNTERS),
                 "historyDays": 14, "historySamples": min(samples) if samples else 0,
                 "historyMax": max(maxima) if maxima else None}
        print(f"\n  USE: of {len(tier_ids)} host(s) with a tier configured, {zero_now} read zero on all "
              f"{len(NVME_COUNTERS)} NVMe-side counters right now")
        print(f"    over {usage['historyDays']} days of daily maxima the largest tier usage seen is "
              f"{usage['historyMax']}, across {usage['historySamples']} sample(s) per host")
        print(f"    meanwhile {dram_live} of them carry live traffic on the DRAM side, so the "
              f"instrumentation is collecting: the tier is configured and idle, not unmeasured")

    # ---- the key set, which is the honest detector
    surface = {}
    if tier_ids and len(tier_ids) < len(ids):
        untier_id = next(r for r in ids if r not in tier_ids)
        kt, ku = statkeys(tok, tier_ids[0]), statkeys(tok, untier_id)
        only = sorted(k for k in (kt - ku) if k.startswith("mem:"))
        surface = {"tieredHostKeys": len(kt), "untieredHostKeys": len(ku), "memKeysOnlyOnTiered": only,
                   "nvmeCapacityKeyOnUntieredHost": NVME_CAP in ku}
        print(f"\n  SURFACE: a configured tier adds {len(only)} mem key(s) the untiered host does not have")
        for k in only:
            print(f"    {k}")
        if surface["nvmeCapacityKeyOnUntieredHost"]:
            print(f"    and {NVME_CAP} is present on the UNTIERED host too, reading zero: "
                  f"its presence is not evidence of a tier")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "gate": GATE, "trigger": TRIGGER, "hosts": rows,
               "candidates": len(cand), "pastTrigger": len(past), "tierConfigured": len(tiered_rows),
               "totalHosts": len(rows),
               "fleetColdDramGiB": round(sum(r["coldDramGiB"] for r in rows), 1),
               "fleetDramGiB": round(sum(r["dramGiB"] for r in rows), 1),
               "denominator": denom, "use": usage, "surface": surface}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    # No host, cluster, or instance name is read into the record: hosts are numbered by consumption
    # rank. Assert it rather than trust it.
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "candidacy.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"\nwrote candidacy.json; hosts are numbered by consumption rank and no name is recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
