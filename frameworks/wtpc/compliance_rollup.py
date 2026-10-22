#!/usr/bin/env python3
"""Cross-posture compliance rollup - one ranked row per posture on a comparable scale.

A Tier-3 evidence surface (read-only). Absolute envelopes differ per posture, so raw ratios cannot be
compared across postures; the ENVELOPE POSITION (observed / breach) normalizes each to its own breach
(1.0 = at breach for EVERY posture), which is the only cross-posture-comparable number - exactly the
triage a per-posture scorecard cannot give, and the reason this is an estate surface, not a view (a
posture is not a vROps object). Ranked strict-first (governance.strictness_key).

Per posture, over its Clusters group:
  worst position = max(worst-host mem overcommit / mem breach ; cluster cpu overcommit / cpu breach)
  compliance %   = member hosts within the capacity envelope / member hosts (R1+R2 = the out-of-envelope count)
  floor          = PASS, unless a member cluster has HA config issues (or, strict, failover below N+1);
                   UNVERIF if the floor observable is missing (never a silent PASS - the precondition row);
                   EMPTY if the Clusters group has no member, so nothing was scored (a membership finding,
                   which the adoption chain audit walks, never a pass)

Exit status: 0 when every live posture has members, sits at or inside its breach and passes its floor; 1 when
one is past its breach, its floor reads BREACH or UNVERIF, or it is EMPTY. A proposed posture with no Clusters
group on the instance is not deployed and is not a finding. `--out FILE` also writes the rows as JSON; posture
names are the framework's own, and no cluster or host is named.

Usage:  python3 compliance_rollup.py [--out rollup.json]   (from this folder; live, read-only)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

from lib._client import ops_client
from lib._names import posture_group, with_aliases
from lib._evidence import latest_stat
from lib._groups import group_members, list_groups
from lib._sm import load_sm_ids, sm_stat_key

import governance   # strictness_key, load_postures - the single source of the rank

HERE = os.path.dirname(os.path.abspath(__file__))


def _num(v):
    try:
        return float(str(v).lstrip("><"))
    except (TypeError, ValueError):
        return None


def _rollup(c, name, doc, groups):
    gid = groups.get(posture_group(name, "Clusters"))
    if not gid:
        return None
    ids = load_sm_ids(os.path.join(HERE, f"supermetrics.{name}.yaml"))
    cap = doc["envelope"]["capacity"]
    mem_breach, cpu_breach = _num(cap["mem_overcommit"]["breach"]), _num(cap["cpu_overcommit"]["breach"])
    n_plus = _num(doc.get("availability_floor", {}).get("n_plus")) or 0
    strict = doc.get("availability_floor", {}).get("ha") == "required"
    members = group_members(c, gid)
    # the posture's MEMBER VM count (its VMs group) - the honest per-posture scale, not cluster VMs (G13),
    # which double-counts a shared cluster across the postures resident on it.
    vgid = groups.get(posture_group(name, "VMs"))
    member_vms = len(group_members(c, vgid)) if vgid else None
    a = {"clusters": 0, "hosts": 0.0, "vms": member_vms, "out": 0.0, "wmem": 0.0, "wcpu": 0.0, "floor_ok": True, "unverif": False}
    for m in members:
        rid = m["identifier"]
        a["clusters"] += 1
        sm = lambda k: latest_stat(c, rid, sm_stat_key(ids[k]))  # noqa: E731
        g7, g6, g12, r1, r2 = sm("G7"), sm("G6"), sm("G12"), sm("R1"), sm("R2")
        cfg = latest_stat(c, rid, "configuration|dasConfig|ha_number_config_issues")
        fail = latest_stat(c, rid, "configuration|dasConfig|currentFailoverLevel")
        if g7 is not None and mem_breach:
            a["wmem"] = max(a["wmem"], g7 / mem_breach)
        if g6 is not None and cpu_breach:
            a["wcpu"] = max(a["wcpu"], g6 / cpu_breach)
        a["hosts"] += g12 or 0
        a["out"] += (r1 or 0) + (r2 or 0)
        if cfg is None:
            a["unverif"] = True
        elif cfg > 0:
            a["floor_ok"] = False
        if strict and fail is not None and fail < max(n_plus, 1):
            a["floor_ok"] = False
    return a


def verdict(a: dict | None) -> tuple[str, bool]:
    """A row's floor and whether it is a finding: EMPTY before anything else, since nothing was scored."""
    if a is None:
        return "-", False                       # a proposed posture, not deployed on this instance
    if not a["clusters"]:
        return "EMPTY", True
    floor = "UNVERIF" if a["unverif"] else ("PASS" if a["floor_ok"] else "BREACH")
    return floor, floor != "PASS" or max(a["wmem"], a["wcpu"]) > 1.0


def row_record(name: str, a: dict | None) -> dict:
    floor, finding = verdict(a)
    if a is None:
        return {"posture": name, "clustersGroup": False, "floor": floor, "finding": finding}
    scored = bool(a["clusters"])
    comp = (1 - a["out"] / a["hosts"]) * 100 if a["hosts"] else None
    return {"posture": name, "clustersGroup": True, "clusters": a["clusters"], "hosts": round(a["hosts"]),
            "memberVms": a["vms"], "worstMem": round(a["wmem"], 2) if scored else None,
            "worstCpu": round(a["wcpu"], 2) if scored else None,
            "hostCompliancePct": round(comp) if comp is not None else None, "floor": floor, "finding": finding}


def main() -> int:
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    postures = governance.load_postures()
    with ops_client() as c:
        groups = with_aliases({g.get("resourceKey", {}).get("name"): g["id"] for g in list_groups(c, include_policy=False)})
        rows = [(name, doc, _rollup(c, name, doc, groups)) for name, doc in postures.items()]
        rows.sort(key=lambda t: governance.strictness_key(t[1]), reverse=True)

        print("CROSS-POSTURE COMPLIANCE ROLLUP  (envelope position: 1.0 = at breach; ranked strict-first)\n")
        print(f"  {'posture':28}{'clusters':>9}{'hosts':>6}{'mVMs':>5}{'worst mem':>11}{'worst cpu':>11}"
              f"{'host compliance':>17}{'floor':>9}")
        print("  " + "-" * 96)
        for name, _doc, a in rows:
            if a is None:
                print(f"  {name:28}{'(no Clusters group live)':>66}")
                continue
            floor, _ = verdict(a)
            vms = f"{a['vms']:.0f}" if a["vms"] is not None else "-"
            if not a["clusters"]:
                print(f"  {name:28}{0:>9}{'-':>6}{vms:>5}{'-':>11}{'-':>11}{'-':>17}{floor:>9}")
                continue
            comp = (1 - a["out"] / a["hosts"]) * 100 if a["hosts"] else None
            print(f"  {name:28}{a['clusters']:>9}{a['hosts']:>6.0f}{vms:>5}"
                  f"{a['wmem']:>11.2f}{a['wcpu']:>11.2f}{(f'{comp:.0f}%' if comp is not None else '-'):>17}{floor:>9}")
        print("\n  Worst position > 1.0 = a member is past its breach; postures compare on this normalized scale, "
              "not on raw ratios (mVMs = the posture's member VMs).\n  A floor BREACH / UNVERIF gates the row - restore the floor before trusting the "
              "tuning triage above it.\n  EMPTY = the posture's Clusters group has no member, so nothing was scored: a "
              "membership finding, not a pass.")
    records = [row_record(name, a) for name, _doc, a in rows]
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"captured_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": records}, f, indent=1)
            f.write("\n")
        print(f"\n  wrote {out}")
    return 1 if any(r["finding"] for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
