#!/usr/bin/env python3
"""candidacy.py: run the memory-tiering lens against your own hosts, read-only.

The chapter teaches a gate and a trigger. This runs both against every host the Operations instance
collects, and reports what the verdict alone does not tell you:

  1. WHERE EACH HOST LANDS. Active as a percent of the DRAM tier against the candidacy gate, and
     consumed as a percent of the DRAM tier against the activation trigger. Two columns, two
     questions, as the chapter insists;
  2. WHAT THE WRONG DENOMINATOR WOULD HAVE COST. The same candidacy percentage recomputed against
     `mem|totalCapacity_average`, per host, with the signed error. The error does not have one sign:
     on a host with a tier configured the total counts the tier and understates; on a host without
     one the total is usable memory net of hypervisor overhead and overstates;
  3. WHICH HOSTS HAVE A TIER, AND WHAT IT HAS HELD, DAY BY DAY. A configured tier and a used tier are
     different facts. For each host with a tier this reads the daily maxima of its NVMe tier usage and
     of its consumption over the window: the first day the tier held pages, its peak, its newest
     value, and how many days the host spent past the trigger before the first page arrived;
  4. WHAT CONSUMED COUNTS ON A TIERED HOST. Host consumed memory is read beside the usage of each
     tier. Where the two tiers' usage adds up to consumed, consumed includes the pages held on NVMe,
     and consumed as a percent of DRAM can pass 100; the DRAM tier's own usage is then the readiness
     numerator that stays inside DRAM;
  5. WHETHER THE 1:1 DEFAULT HOLDS. The uplift a 1:1 ratio would give you, against the tier size
     the host reports. Where those disagree, every number derived from the assumption inherits the
     error.

DETECTING A TIER. `mem:NVMe|memory_tier_total_capacity` is the wrong key for this: it can be present
on every host, reading zero where there is no tier, so its presence proves nothing, and where it is
non-zero it need not equal the tier's size. The key that discriminates is `mem:NVMe|memory_tier_size`,
and the cleanest detector of all is the key set: the keys on every host with a tier and on no host
without one (a tier size, a tier usage, and read and write latency and bandwidth on the NVMe side).
Every host's key list is read, because a key on one untiered host may be missing from another.

ONLY HOSTS THAT EXIST. A host the instance no longer collects keeps its resource and its last
values. A host is measured only when none of its adapter states reads NOT_EXISTING and its newest
consumption sample is younger than an hour; the rest are counted as skipped, with the reason.

UNITS. `mem|` keys and the DRAM tier capacity read in KB; `tier.usage` reads in MB, which the
consumed check in (4) confirms on your own hosts when the two tiers add up.

Read-only throughout: resource lists, relationships, properties, stat keys and stat values. It writes
nothing to the instance. No host, cluster or instance name is read into the record: hosts are
numbered by consumption rank.

Run:
  umask 077                                   # files you create from here on are mode 0600
  export OPS_HOST=... OPS_BROKER_HOST=... OPS_API_TOKEN_FILE=./ops.token   # the token file, mode 0600
  export OPS_TLS_VERIFY=false                 # only on a self-signed lab CA
  python3 candidacy.py [--days 60]            # writes candidacy.json beside this file (OUT_DIR moves it)
"""

from __future__ import annotations

import argparse
import calendar
import collections
import json
import os
import re
import sys
import time

from opslib import bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

GATE = float(os.environ.get("MEMTIER_GATE", "50"))       # active pct of DRAM: the candidacy gate
TRIGGER = float(os.environ.get("MEMTIER_TRIGGER", "80"))  # consumed pct of DRAM: tiering begins
STALE_MINUTES = 60                                        # an older newest sample is not a live host

ACTIVE = "mem|active_average"
CONSUMED = "mem|consumed_average"
DRAM_CAP = "mem:DRAM|memory_tier_total_capacity"
NVME_CAP = "mem:NVMe|memory_tier_total_capacity"
NVME_SIZE = "mem:NVMe|memory_tier_size"
NVME_USED = "mem:NVMe|tier.usage"
DRAM_USED = "mem:DRAM|tier.usage"
TOTAL_CAP = "mem|totalCapacity_average"
GUEST_DEMAND = "mem|guest_demand"
SIGNALS = [ACTIVE, CONSUMED, DRAM_CAP, NVME_CAP, NVME_SIZE, NVME_USED, DRAM_USED, TOTAL_CAP,
           "mem|granted_average"]

# The counters that only exist on a host with a tier configured. Every one of them reads on the
# NVMe side of the boundary, which is what makes them a fair test of whether the tier carries load.
NVME_COUNTERS = [NVME_USED, "mem:NVMe|latency.read_latest", "mem:NVMe|latency.write_latest",
                 "mem:NVMe|bandwidth.read_latest", "mem:NVMe|bandwidth.write_latest"]
DRAM_COUNTERS = ["mem:DRAM|latency.read_latest", "mem:DRAM|bandwidth.read_latest"]

KB_PER_GIB, MB_PER_GIB = 1048576, 1024


def latest(tok, ids, keys):
    """{resourceId: {statKey: (newest value, its time in epoch ms)}} for a batch of resources."""
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   {"resourceId": ids, "statKey": keys})
    if st != 200:
        raise SystemExit(f"stat query returned HTTP {st}")
    out = {}
    for v in (body or {}).get("values") or []:
        d = {}
        for s in v.get("stat-list", {}).get("stat", []):
            k, data, ts = s.get("statKey", {}).get("key"), (s.get("data") or []), (s.get("timestamps") or [])
            if k and data:
                d[k] = (data[-1], ts[-1] if ts else 0)
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


def daily(tok, rid, keys, days):
    """{statKey: [(UTC date, daily maximum)]} for one resource over the window, oldest first. Daily
    maxima keep a momentary zero from being read as a sustained one."""
    end = int(time.time() * 1000)
    st, body = ops("POST", "/api/resources/stats/query", tok,
                   {"resourceId": [rid], "statKey": keys, "begin": end - days * 86400 * 1000,
                    "end": end, "rollUpType": "MAX", "intervalType": "DAYS",
                    "intervalQuantifier": 1})
    if st != 200:
        return {}
    out = {}
    for v in (body or {}).get("values") or []:
        for s in v.get("stat-list", {}).get("stat", []):
            day = [time.strftime("%Y-%m-%d", time.gmtime(t / 1000)) for t in s.get("timestamps") or []]
            out[s["statKey"]["key"]] = list(zip(day, s.get("data") or [], strict=False))
    return out


def share_past_trigger(tok, rid, begin_ms, end_ms, dram_kb):
    """The percent of five-minute consumption samples at or past the trigger between two times, and how many
    samples that is: a daily maximum past the trigger can be one spike, and a share says whether it was sustained."""
    st, body = ops("POST", "/api/resources/stats/query", tok,
                   {"resourceId": [rid], "statKey": [CONSUMED], "begin": begin_ms, "end": end_ms,
                    "rollUpType": "AVG", "intervalType": "MINUTES", "intervalQuantifier": 5})
    data = [x for v in ((body or {}).get("values") or []) if st == 200
            for s in v.get("stat-list", {}).get("stat", []) for x in s.get("data") or []]
    if not data:
        return None
    past = sum(1 for x in data if 100 * x / dram_kb >= TRIGGER)
    return {"samples": len(data), "atOrPastTrigger": past, "pctAtOrPastTrigger": round(100 * past / len(data), 1)}


def first_sample(tok, rid, day, dram_kb):
    """The first five-minute sample on a UTC day with pages in the NVMe tier, the tier's size in it, and
    consumption (percent of DRAM) in it and in the sample before. None when that day's samples are gone."""
    begin = (calendar.timegm(time.strptime(day, "%Y-%m-%d")) - 3600) * 1000   # from an hour before the day
    st, body = ops("POST", "/api/resources/stats/query", tok,
                   {"resourceId": [rid], "statKey": [NVME_USED, CONSUMED], "begin": begin,
                    "end": begin + 26 * 3600 * 1000, "rollUpType": "AVG", "intervalType": "MINUTES",
                    "intervalQuantifier": 5})
    if st != 200:
        return None
    ser = {}
    for v in (body or {}).get("values") or []:
        for s in v.get("stat-list", {}).get("stat", []):
            ser[s["statKey"]["key"]] = dict(zip(s.get("timestamps") or [], s.get("data") or [], strict=False))
    used, cons = ser.get(NVME_USED) or {}, ser.get(CONSUMED) or {}
    first = next((t for t in sorted(used) if used[t]), None)
    if first is None:
        return None
    prior = [t for t in sorted(cons) if t < first]
    return {"at": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(first / 1000)),
            "tierGiB": round(used[first] / MB_PER_GIB, 1),
            "consumedPctOfDram": round(100 * cons[first] / dram_kb, 1) if first in cons else None,
            "consumedPctOfDramSampleBefore": round(100 * cons[prior[-1]] / dram_kb, 1) if prior else None}


def builds(tok, ids):
    """{resourceId: ESX version string} from the hosts' summary|version property."""
    st, body = ops("POST", "/api/resources/properties/latest/query", tok,
                   {"resourceIds": ids, "propertyKeys": ["summary|version"]})
    out = {}
    if st == 200:
        for v in (body or {}).get("values") or []:
            for p in (v.get("property-contents") or {}).get("property-content") or []:
                if p.get("statKey") == "summary|version" and p.get("values"):
                    out[v["resourceId"]] = p["values"][-1]
    return out


def cluster_of(tok, rid):
    """The id of the cluster a host belongs to, from its PARENT relationships; None when it has none."""
    st, body = ops("GET", f"/api/resources/{rid}/relationships/PARENT", tok, params={"_no_links": "true"})
    if st != 200:
        return None
    for r in (body or {}).get("resourceList") or []:
        if (r.get("resourceKey") or {}).get("resourceKindKey") == "ClusterComputeResource":
            return r.get("identifier")
    return None


def tier_use(series, dram_kb):
    """The tier's history for one host, from its daily maxima."""
    used = series.get(NVME_USED) or []
    cons = dict(series.get(CONSUMED) or [])
    with_pages = [(d, mb) for d, mb in used if mb]
    first = with_pages[0][0] if with_pages else None
    before = [d for d, _ in used if first is None or d < first]
    pct_before = [100 * cons[d] / dram_kb for d in before if d in cons]
    peak = max(used, key=lambda x: x[1]) if used else None
    return {"daysRead": len(used),
            "daysWithPages": len(with_pages),
            "firstDayWithPages": first,
            "peakTierGiB": round(peak[1] / MB_PER_GIB, 1) if peak else None,
            "peakDay": peak[0] if peak and peak[1] else None,
            "lastDayTierGiB": round(used[-1][1] / MB_PER_GIB, 1) if used else None,
            "consumedPctOfDramPeakBeforePages": round(max(pct_before), 1) if pct_before else None,
            "daysPastTriggerBeforePages": sum(1 for p in pct_before if p >= TRIGGER),
            "consumedPctOfDramPeak": round(max(100 * v / dram_kb for v in cons.values()), 1) if cons else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="The memory-tiering lens, read-only, against your own hosts.")
    ap.add_argument("--days", type=int, default=60,
                    help="days of daily maxima to read for each host with a tier (1 to 365; default 60)")
    args = ap.parse_args(argv)
    if not 1 <= args.days <= 365:
        ap.error("--days takes 1 to 365")
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    tok = bearer()
    print("candidacy.py: the memory-tiering lens, run against your own hosts\n")

    st, body = ops("GET", "/api/resources", tok,
                   params={"resourceKind": "HostSystem", "pageSize": 1000, "_no_links": "true"})
    if st != 200:
        raise SystemExit(f"host list returned HTTP {st}")
    listed = [h for h in ((body or {}).get("resourceList") or []) if h.get("identifier")]
    if not listed:
        raise SystemExit("no HostSystem resources; nothing to measure")
    vals = latest(tok, [h["identifier"] for h in listed], SIGNALS)

    # ---- only hosts that exist: no adapter reads NOT_EXISTING, and the newest sample is recent
    now = time.time() * 1000
    skipped = collections.Counter()
    ids = []
    for h in listed:
        states = [s.get("resourceState") for s in h.get("resourceStatusStates") or []]
        newest = (vals.get(h["identifier"], {}).get(CONSUMED) or (None, 0))[1]
        if "NOT_EXISTING" in states:
            skipped["an adapter reads NOT_EXISTING"] += 1
        elif now - newest > STALE_MINUTES * 60000:
            skipped[f"no consumption sample in the last {STALE_MINUTES} minutes"] += 1
        else:
            ids.append(h["identifier"])
    print(f"  hosts listed: {len(listed)}; measured: {len(ids)}"
          + "".join(f"; skipped, {why}: {n}" for why, n in skipped.items()))
    if not ids:
        raise SystemExit("no live HostSystem resources; nothing to measure")
    v = {rid: {k: x[0] for k, x in vals.get(rid, {}).items()} for rid in ids}
    version = builds(tok, ids)

    rows, rank = [], {}
    for n, rid in enumerate(sorted(ids, key=lambda r: -(v[r].get(CONSUMED) or 0)), 1):
        d = v[rid]
        a, con, dram, tot = d.get(ACTIVE), d.get(CONSUMED), d.get(DRAM_CAP), d.get(TOTAL_CAP)
        if a is None or con is None or not dram:
            print(f"  host {n}: skipped, one of active/consumed/DRAM-capacity did not read")
            continue
        rank[rid] = n
        tier_size = d.get(NVME_SIZE) or 0
        row = {"host": n,
               "activePctOfDram": round(100 * a / dram, 1),
               "consumedPctOfDram": round(100 * con / dram, 1),
               "candidate": (100 * a / dram) < GATE,
               "pastTrigger": (100 * con / dram) >= TRIGGER,
               "coldDramGiB": round((con - a) / KB_PER_GIB, 1),
               "dramGiB": round(dram / KB_PER_GIB, 1),
               "tierConfigured": bool(tier_size),
               "tierGiB": round(tier_size / KB_PER_GIB, 1) if tier_size else 0,
               "esx": version.get(rid),
               # The NVMe capacity key, recorded precisely because it is NOT a tier detector.
               "nvmeCapacityKeyReads": d.get(NVME_CAP)}
        if tot:
            wrong = 100 * a / tot
            row["activePctOfTotal"] = round(wrong, 1)
            row["denominatorErrorPct"] = round((wrong - 100 * a / dram) / (100 * a / dram) * 100, 1)
        if tier_size:
            # The 1:1 default, measured rather than assumed.
            row["upliftIfOneToOneGiB"] = round(dram / KB_PER_GIB, 1)
            row["ratioDramToTier"] = round(tier_size / dram, 3)
            # What consumed counts: the two tiers' usage (MB) against consumed (KB).
            dram_mb, nvme_mb = d.get(DRAM_USED), d.get(NVME_USED)
            if dram_mb is not None and nvme_mb is not None and con:
                row["tierUsageGiB"] = {"dram": round(dram_mb / MB_PER_GIB, 1), "nvme": round(nvme_mb / MB_PER_GIB, 1)}
                row["consumedMinusBothTiersPct"] = round(100 * (con - (dram_mb + nvme_mb) * 1024) / con, 2) + 0.0  # no -0.0
                row["dramOnlyPctOfDram"] = round(100 * dram_mb * 1024 / dram, 1)
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
              + (f"  tier {r['tierGiB']:.1f} GiB (ratio 1:{r['ratioDramToTier']:g})" if r["tierConfigured"] else ""))
    esx = collections.Counter(r["esx"] for r in rows)
    print("    ESX versions: " + ", ".join(f"{k} on {n}" for k, n in esx.items()))

    # ---- the denominator, in both directions
    errs = [r for r in rows if "denominatorErrorPct" in r]
    t_err = [r["denominatorErrorPct"] for r in errs if r["tierConfigured"]]
    u_err = [r["denominatorErrorPct"] for r in errs if not r["tierConfigured"]]
    denom = {"tieredHosts": t_err, "untieredHosts": u_err,
             "changesSign": bool(t_err and u_err and min(u_err) > 0 > max(t_err))}
    print("\n  DENOMINATOR: recomputing candidacy against total capacity instead of the DRAM tier")
    if t_err:
        print(f"    on a host WITH a tier:    {min(t_err):+.1f}% to {max(t_err):+.1f}%  (the total counts the tier: understates)")
    if u_err:
        print(f"    on a host WITHOUT a tier: {min(u_err):+.1f}% to {max(u_err):+.1f}%  (the total is net of overhead: overstates)")
    if denom["changesSign"]:
        print("    the error CHANGES SIGN at activation, so a single correction factor cannot fix it")

    # ---- what each tier has held, day by day, and what consumed counts
    tier_ids = [rid for rid in rank if v[rid].get(NVME_SIZE)]
    usage = {}
    if tier_ids:
        live = latest(tok, tier_ids, NVME_COUNTERS + DRAM_COUNTERS)
        zero_now = sum(1 for rid in tier_ids
                       if all(not (live.get(rid, {}).get(k) or (0,))[0] for k in NVME_COUNTERS))
        dram_live = sum(1 for rid in tier_ids
                        if any((live.get(rid, {}).get(k) or (0,))[0] for k in DRAM_COUNTERS))
        clusters = {rid: cluster_of(tok, rid) for rid in rank}
        per = []
        for rid in sorted(tier_ids, key=lambda r: rank[r]):
            row = next(r for r in rows if r["host"] == rank[rid])
            h = {"host": rank[rid], "ratioDramToTier": row["ratioDramToTier"]}
            h.update(tier_use(daily(tok, rid, [NVME_USED, CONSUMED], args.days), v[rid][DRAM_CAP]))
            if h["firstDayWithPages"]:
                h["firstSampleWithPages"] = first_sample(tok, rid, h["firstDayWithPages"], v[rid][DRAM_CAP])
            # how much of the time before the first page (or of the whole window) the host sat past the trigger
            end_ms = int(time.time() * 1000)
            fs = h.get("firstSampleWithPages")
            stop = calendar.timegm(time.strptime(fs["at"], "%Y-%m-%dT%H:%MZ")) * 1000 if fs else end_ms
            h["fiveMinuteSampleShareBeforePages"] = share_past_trigger(
                tok, rid, end_ms - args.days * 86400 * 1000, stop, v[rid][DRAM_CAP])
            c = clusters.get(rid)
            if c:
                mates = [r for r, cl in clusters.items() if cl == c]
                h["clusterHosts"] = len(mates)
                h["clusterHostsWithTier"] = sum(1 for r in mates if r in tier_ids)
                h["clusterEsxVersions"] = len({version.get(r) for r in mates})
            per.append(h)
        usage = {"tieredHosts": len(tier_ids), "everyNvmeCounterZeroNow": zero_now,
                 "dramSideCarryingTraffic": dram_live, "nvmeCounters": len(NVME_COUNTERS),
                 "days": args.days, "hosts": per}
        print(f"\n  USE: of {len(tier_ids)} host(s) with a tier configured, {zero_now} read zero on all "
              f"{len(NVME_COUNTERS)} NVMe-side counters right now, and {dram_live} carry live DRAM-side traffic")
        for h in per:
            sh = h.get("fiveMinuteSampleShareBeforePages")
            share = (f"; {sh['atOrPastTrigger']} of {sh['samples']} five-minute samples ({sh['pctAtOrPastTrigger']}%) "
                     f"{'before the first page ' if h['firstDayWithPages'] else ''}at or past the trigger") if sh else ""
            if h["firstDayWithPages"]:
                print(f"    host {h['host']:>2} (1:{h['ratioDramToTier']:g}): pages in the tier on {h['daysWithPages']} of "
                      f"{h['daysRead']} days, first on {h['firstDayWithPages']}; peak {h['peakTierGiB']} GiB on {h['peakDay']}, "
                      f"{h['lastDayTierGiB']} GiB on the last day")
                print(f"      before the first page: {h['daysPastTriggerBeforePages']} day(s) at or past the "
                      f"{TRIGGER:.0f} trigger, peak consumption {h['consumedPctOfDramPeakBeforePages']}% of DRAM{share}")
                f = h.get("firstSampleWithPages")
                if f:
                    print(f"      first five-minute sample with pages: {f['at']}, {f['tierGiB']} GiB in the tier, consumption "
                          f"{f['consumedPctOfDram']}% of DRAM (the sample before: {f['consumedPctOfDramSampleBefore']}%)")
            else:
                print(f"    host {h['host']:>2} (1:{h['ratioDramToTier']:g}): no page in the tier on any of {h['daysRead']} days; "
                      f"{h['daysPastTriggerBeforePages']} day(s) at or past the {TRIGGER:.0f} trigger, "
                      f"peak consumption {h['consumedPctOfDramPeak']}% of DRAM{share}")
        for r in tiered_rows:
            if "consumedMinusBothTiersPct" in r:
                print(f"    host {r['host']:>2}: consumed {r['consumedPctOfDram']}% of DRAM; DRAM tier {r['tierUsageGiB']['dram']} GiB "
                      f"+ NVMe tier {r['tierUsageGiB']['nvme']} GiB differs from consumed by {r['consumedMinusBothTiersPct']}%; "
                      f"DRAM alone is {r['dramOnlyPctOfDram']}% of DRAM")

    # ---- the key set, which is the honest detector, and the object types each key lives on.
    # Every measured host's key list is read: a key a tier brings must be on every host with a tier
    # and on no host without one, and one untiered host is not every untiered host.
    surface = {}
    if tier_ids and len(tier_ids) < len(rank):
        keys = {rid: statkeys(tok, rid) for rid in rank}
        untiered = [r for r in rank if r not in tier_ids]
        on_every_tiered = set.intersection(*(keys[r] for r in tier_ids))
        on_any_untiered = set().union(*(keys[r] for r in untiered))
        only = sorted(k for k in on_every_tiered - on_any_untiered if k.startswith("mem:"))
        shared = {k: sum(1 for r in untiered if k in keys[r])
                  for k in sorted(on_every_tiered & on_any_untiered) if k.startswith("mem:")}
        cap = {r: v[r].get(NVME_CAP) for r in rank}
        surface = {"memKeysOnlyOnTiered": only,
                   "memKeysAlsoOnSomeUntiered": {k: n for k, n in shared.items() if n < len(untiered)},
                   "untieredHosts": len(untiered),
                   "hostKeyCounts": [min(len(k) for k in keys.values()), max(len(k) for k in keys.values())],
                   "nvmeCapacityKeyPresentOn": sum(1 for r in rank if NVME_CAP in keys[r]),
                   "nvmeCapacityKeyNonZeroOn": sum(1 for r in rank if cap[r]),
                   "nvmeCapacityKeyGiBOnTiered": sorted({round(cap[r] / KB_PER_GIB, 1) for r in tier_ids if cap[r]}),
                   "guestDemandOnHost": any(GUEST_DEMAND in keys[r] for r in rank),
                   "dramCapacityOnHost": all(DRAM_CAP in keys[r] for r in rank)}
        st, vb = ops("GET", "/api/resources", tok,
                     params={"resourceKind": "VirtualMachine", "pageSize": 50, "_no_links": "true"})
        vm = next((x for x in ((vb or {}).get("resourceList") or [])
                   if "NOT_EXISTING" not in [s.get("resourceState") for s in x.get("resourceStatusStates") or []]), None)
        if vm:
            kv = statkeys(tok, vm["identifier"])
            surface.update({"vmKeys": len(kv), "guestDemandOnVm": GUEST_DEMAND in kv,
                            "dramCapacityOnVm": DRAM_CAP in kv})
        print(f"\n  SURFACE: {len(only)} mem key(s) are on every host with a tier and on none of the "
              f"{len(untiered)} without one")
        for k in only:
            print(f"    {k}")
        for k, n in surface["memKeysAlsoOnSomeUntiered"].items():
            print(f"    not a detector: {k} is also on {n} of the {len(untiered)} untiered host(s)")
        print(f"    {NVME_CAP} is present on {surface['nvmeCapacityKeyPresentOn']} host(s) and non-zero on "
              f"{surface['nvmeCapacityKeyNonZeroOn']}, reading {surface['nvmeCapacityKeyGiBOnTiered']} GiB on the "
              f"tiered ones: compare that with their tier sizes above before reading it as the tier")
        if vm:
            print(f"    {GUEST_DEMAND}: on a VM {surface['guestDemandOnVm']}, on a host {surface['guestDemandOnHost']}; "
                  f"{DRAM_CAP}: on a VM {surface['dramCapacityOnVm']}, on a host {surface['dramCapacityOnHost']}")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "gate": GATE, "trigger": TRIGGER, "hostsListed": len(listed),
               "hostsSkipped": dict(skipped), "hosts": rows,
               "candidates": len(cand), "pastTrigger": len(past), "tierConfigured": len(tiered_rows),
               "totalHosts": len(rows), "esxVersions": dict(esx),
               "fleetColdDramGiB": round(sum(r["coldDramGiB"] for r in rows), 1),
               "fleetDramGiB": round(sum(r["dramGiB"] for r in rows), 1),
               "denominator": denom, "use": usage, "surface": surface}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    # No host, cluster, or instance name is read into the record: hosts are numbered by consumption
    # rank. Assert it rather than trust it.
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        val = os.environ.get(var)
        if val and val in text:
            raise SystemExit(f"{var} reached the record; nothing was written")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "candidacy.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nwrote candidacy.json; hosts are numbered by consumption rank and no name is recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
