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
                   UNVERIF if the floor observable is missing (never a silent PASS - the precondition row)

Usage:  python compliance_rollup.py   (from deploy/vcf-ops-content/wtpc/; live, read-only)
"""
from __future__ import annotations

import os
import sys

from lib._client import ops_client
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
    gid = groups.get(f"PCA - WTPC - Group - {name} (Clusters)")
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
    vgid = groups.get(f"PCA - WTPC - Group - {name} (VMs)")
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


def main() -> int:
    postures = governance.load_postures()
    with ops_client() as c:
        groups = {g.get("resourceKey", {}).get("name"): g["id"] for g in list_groups(c, include_policy=False)}
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
            comp = (1 - a["out"] / a["hosts"]) * 100 if a["hosts"] else None
            floor = "UNVERIF" if a["unverif"] else ("PASS" if a["floor_ok"] else "BREACH")
            vms = f"{a['vms']:.0f}" if a["vms"] is not None else "-"
            print(f"  {name:28}{a['clusters']:>9}{a['hosts']:>6.0f}{vms:>5}"
                  f"{a['wmem']:>11.2f}{a['wcpu']:>11.2f}{(f'{comp:.0f}%' if comp is not None else '-'):>17}{floor:>9}")
        print("\n  Worst position > 1.0 = a member is past its breach; postures compare on this normalized scale, "
              "not on raw ratios (mVMs = the posture's member VMs).\n  A floor BREACH / UNVERIF gates the row - restore the floor before trusting the "
              "tuning triage above it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
