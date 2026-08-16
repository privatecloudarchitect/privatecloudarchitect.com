#!/usr/bin/env python3
"""Shared-infrastructure governance primitives — the executable half of the framework's
shared-infrastructure governance doctrine.

Two things live here, both derived from the posture envelopes (the portable source of truth):

1. **Axis-precedence strictness key** — a total order over postures by the declared axis precedence
   Availability > Performance > Capacity (Cost is EXCLUDED — priced, not policed). Stricter posture =
   higher key. This is what makes "strictest-resident-wins" deterministic: rank the global policy
   priority list by this key and VCF Operations' highest-priority-wins selects the right policy with no
   human choice (Policy Doctrine P3, extended).

2. **Envelope feasibility** — a pure per-axis test of whether two postures can co-exist on one host.
   The density/overcommit axis is where they conflict: if posture A's TARGET overcommit exceeds posture
   B's BREACH, you cannot pack to A's target without breaching B (the test-dev <-> prod-db inversion).
   An infeasible pair is a re-placement signal, never a silently-composed policy.

CLI:
  python governance.py                     # print the strictness ranking of the committed postures
  python governance.py --priority-parity   # LIVE: assert the global policy order is strict-first (P4 sibling)
  python governance.py --config-parity     # LIVE: assert each policy's capacity settings match the catalog (C2)
  python governance.py --self-test         # exercise the feasibility check (prod-db vs the catalog's test-dev)
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POSTURES_DIR = os.path.join(HERE, "postures")
POLICY_PREFIX = "PCA - WTPC - Policy - "

# Axis precedence (Cost deliberately excluded from the GOVERNING rank — see the governance doctrine).
AXIS_PRECEDENCE = ("availability", "performance", "capacity")


def _num(v):
    """Parse a threshold that may be a number or a '>0' / '<5' string -> float, else None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lstrip("><").strip()
    try:
        return float(s)
    except ValueError:
        return None


def load_postures() -> dict:
    """{posture-name: parsed-yaml} for every committed posture source."""
    import yaml
    out = {}
    for path in sorted(glob.glob(os.path.join(POSTURES_DIR, "*.yaml"))):
        doc = yaml.safe_load(open(path, encoding="utf-8"))
        if doc and doc.get("posture"):
            out[doc["posture"]] = doc
    return out


# --- strictness (higher = stricter, per axis) --------------------------------------------------

def availability_strictness(floor: dict) -> float:
    if not floor:
        return 0.0
    s = 0.0
    if floor.get("ha") == "required":
        s += 10
    if floor.get("ha_admission_control") == "enabled":
        s += 10
    s += 2 * (_num(floor.get("n_plus")) or 0)
    if floor.get("drs_minimum") == "fully_automated":
        s += 2
    hc = _num(floor.get("headroom_ceiling_pct"))
    if hc is not None:                      # lower ceiling = less consumption allowed = stricter
        s += (100 - hc) / 100.0
    if floor.get("anti_affinity") not in (None, "none", "", False):
        s += 1
    return s


def performance_strictness(perf: dict) -> float:
    """Tighter breach thresholds = stricter -> negate the mean breach (lower breach => higher score)."""
    if not perf:
        return 0.0
    keys = ("cpu_ready_pct_p95", "cpu_costop_pct_p95", "mem_contention_pct_p95", "mem_balloon_pct_p95")
    vals = [_num(perf.get(k, {}).get("breach")) for k in keys]
    vals = [v for v in vals if v is not None]
    return -(sum(vals) / len(vals)) if vals else 0.0


def capacity_strictness(cap: dict) -> float:
    """Lower overcommit breach = stricter (memory weighted, it is the DB axis) -> negate."""
    if not cap:
        return 0.0
    mem = _num(cap.get("mem_overcommit", {}).get("breach"))
    cpu = _num(cap.get("cpu_overcommit", {}).get("breach"))
    parts = []
    if mem is not None:
        parts.append(-mem * 2)
    if cpu is not None:
        parts.append(-cpu)
    return sum(parts) / len(parts) if parts else 0.0


def strictness_key(posture: dict) -> tuple:
    """Lexicographic (availability, performance, capacity) — higher tuple = stricter posture."""
    env = posture.get("envelope", {}) or {}
    return (
        round(availability_strictness(posture.get("availability_floor", {})), 4),
        round(performance_strictness(env.get("performance", {})), 4),
        round(capacity_strictness(env.get("capacity", {})), 4),
    )


# --- feasibility (can two postures share one host?) --------------------------------------------

def envelope_conflicts(a: dict, b: dict) -> list:
    """Axes where a and b cannot co-exist: one posture's TARGET density breaches the other's envelope."""
    out = []
    ca = (a.get("envelope", {}) or {}).get("capacity", {}) or {}
    cb = (b.get("envelope", {}) or {}).get("capacity", {}) or {}
    for axis in ("mem_overcommit", "cpu_overcommit"):
        at, ab = _num(ca.get(axis, {}).get("target")), _num(ca.get(axis, {}).get("breach"))
        bt, bb = _num(cb.get(axis, {}).get("target")), _num(cb.get(axis, {}).get("breach"))
        if None in (at, ab, bt, bb):
            continue
        if at > bb:
            out.append((axis, f"{a['posture']} target {at} > {b['posture']} breach {bb}"))
        elif bt > ab:
            out.append((axis, f"{b['posture']} target {bt} > {a['posture']} breach {ab}"))
    return out


# --- live: priority-order parity (Policy Doctrine P4 sibling) -----------------------------------

def priority_parity(postures: dict) -> int:
    """Assert the live global policy priority order is strict-first for the posture policies, and that
    every posture policy outranks any non-posture, non-Default policy that could shadow it."""
    from lib._client import ops_client
    with ops_client() as c:
        summaries = c.get("/internal/policies", params={"pageSize": 500}).json()["policy-summaries"]

    posture_live = []   # (priority, posture-name)
    other_ranked = []   # (priority, name) non-posture, non-Default with a priority
    for p in summaries:
        nm, prio = p.get("name", ""), p.get("priority")
        if nm.startswith(POLICY_PREFIX):
            posture_live.append((prio, nm[len(POLICY_PREFIX):]))
        elif prio is not None and not p.get("defaultPolicy"):
            other_ranked.append((prio, nm))

    if not posture_live:
        print("no posture policies live yet — nothing to rank")
        return 0

    print("posture policies · live priority vs strictness rank (1 = highest precedence):")
    resolvable = [(prio, pn) for prio, pn in posture_live if pn in postures]
    unknown = [pn for _, pn in posture_live if pn not in postures]
    # expected order: strictest first
    expected = sorted(resolvable, key=lambda t: strictness_key(postures[t[1]]), reverse=True)
    live_order = sorted(resolvable, key=lambda t: (t[0] if t[0] is not None else 1e9))
    for prio, pn in live_order:
        print(f"  prio={prio!s:>4}  {pn}   strictness={strictness_key(postures[pn])}")
    for pn in unknown:
        print(f"  (no committed posture source for {pn!r} — strictness not checkable)")

    rc = 0
    if [pn for _, pn in live_order] != [pn for _, pn in expected]:
        print("\n❌ live priority order does NOT match strictness order (stricter posture must rank higher).")
        print(f"   expected strict-first: {[pn for _, pn in expected]}")
        rc = 2
    else:
        print("\n✅ posture policies are ranked strict-first (deterministic strictest-resident-wins).")

    # any non-posture ranked ABOVE the least-strict posture policy is a potential shadow (warn; run_parity confirms)
    if other_ranked and posture_live:
        worst_posture_prio = max(prio for prio, _ in posture_live if prio is not None)
        shadow_risk = [(prio, nm) for prio, nm in other_ranked if prio is not None and prio < worst_posture_prio]
        if shadow_risk:
            print("\n⚠️  non-posture policies ranked above a posture policy (potential shadow — confirm with "
                  "validate_live.py --parity):")
            for prio, nm in sorted(shadow_risk):
                print(f"     prio={prio}  {nm}")
    return rc


# --- live: config-drift parity (C2 - the policy "ruler" itself must not drift) ------------------

_ALLOC_KEYS = ("cpu", "memory", "diskspace", "poweredOffVmsConsidered")


def config_parity(postures: dict) -> int:
    """Assert each posture policy's LIVE capacity-allocation settings still match the committed applied
    payload (policy-capacity-allocation.<posture>.json). This is the C2 check the parity trilogy was
    missing: --priority-parity guards the policy ORDER and validate_live.py --parity guards which policy
    is EFFECTIVE, but neither catches the ruler itself drifting - a hand-edit of an allocation ratio or
    buffer in the UI silently re-bases every score beneath it, so a green scorecard can be green against a
    moved envelope. Read-only: GET /api/policies/{id}/settings (the read side of the build's PATCH)."""
    import json
    from lib._client import ops_client, policy_index
    with ops_client() as c:
        live = policy_index(c)
        rc, checked = 0, 0
        print("posture policies · live capacity-allocation vs the applied payload (the catalog ruler):")
        for name in sorted(postures):
            ref_path = os.path.join(HERE, f"policy-capacity-allocation.{name}.json")
            if not os.path.exists(ref_path):
                continue
            pid = live.get(POLICY_PREFIX + name)
            if not pid:
                print(f"  {name}: policy not live yet - skipped")
                continue
            checked += 1
            ref = json.load(open(ref_path, encoding="utf-8"))
            ref_alloc = ref["capacitySettings"]["capacity"]["capacityAllocationSettings"][0]["capacityAllocation"]
            # includeInherited=true reads the EFFECTIVE allocation (own or inherited) - the ratios that
            # actually govern the object. A policy that never applied its own allocation inherits a parent's,
            # which is exactly the silent drift to catch (e.g. a density posture inheriting a strict ratio).
            got = c.get(f"/api/policies/{pid}/settings",
                        params={"type": "CAPACITY_ALLOCATION_MODEL", "resourceKind": "ClusterComputeResource",
                                "adapterKind": "VMWARE", "includeInherited": "true", "_no_links": "true"}).json()
            settings = got.get("capacitySettings", {}).get("capacity", {}).get("capacityAllocationSettings", [])
            own = c.get(f"/api/policies/{pid}/settings",
                        params={"type": "CAPACITY_ALLOCATION_MODEL", "resourceKind": "ClusterComputeResource",
                                "adapterKind": "VMWARE", "_no_links": "true"}).json()
            has_own = bool(own.get("capacitySettings", {}).get("capacity", {}).get("capacityAllocationSettings", []))
            if not settings:
                print(f"  ❌ {name}: no effective capacity-allocation at all (expected {ref_alloc})")
                rc = 2
                continue
            live_alloc = settings[0]["capacityAllocation"]
            diffs = [(k, ref_alloc.get(k), live_alloc.get(k)) for k in _ALLOC_KEYS
                     if ref_alloc.get(k) != live_alloc.get(k)]
            src = "own" if has_own else "INHERITED - the posture never applied its own allocation"
            if diffs:
                rc = 2
                print(f"  ❌ {name}: effective capacity-allocation DRIFTED from the catalog ({src}):")
                for k, want, got_v in diffs:
                    print(f"       {k}: catalog {want}  ->  live {got_v}")
            else:
                print(f"  ✅ {name}: in parity (cpu={live_alloc['cpu']}, mem={live_alloc['memory']}, "
                      f"disk={live_alloc['diskspace']}; {src})")
    if not checked:
        print("  no posture policy with an applied capacity payload is live - nothing to check")
    else:
        print(f"\n{'✅ all ' + str(checked) + ' posture policies in settings-parity' if rc == 0 else '❌ policy settings have drifted from the catalog'} "
              "(C2 - the sibling to --priority-parity / validate_live.py --parity).")
    return rc


def self_test() -> int:
    """Exercise the feasibility check: prod-latency-critical-db vs the catalog's test-dev envelope."""
    postures = load_postures()
    a = postures.get("prod-latency-critical-db")
    if not a:
        raise SystemExit("prod-latency-critical-db.yaml not found")
    # the catalog's test-dev-traditional envelope (the catalog / the catalog) — hot-and-cheap, the P1 inverse
    b = {"posture": "test-dev-traditional",
         "availability_floor": {"ha": "restartable"},
         "envelope": {"capacity": {"mem_overcommit": {"target": 2.0, "warn": 3.0, "breach": 4.0},
                                   "cpu_overcommit": {"target": 4.0, "warn": 6.0, "breach": 8.0}},
                      "performance": {"cpu_ready_pct_p95": {"target": 5, "warn": 10, "breach": 15}}}}
    print(f"strictness  {a['posture']:26} = {strictness_key(a)}")
    print(f"strictness  {b['posture']:26} = {strictness_key(b)}")
    assert strictness_key(a) > strictness_key(b), "prod-db must outrank test-dev"
    conflicts = envelope_conflicts(a, b)
    print(f"\nfeasibility(prod-db, test-dev): {len(conflicts)} conflict axis/axes")
    for axis, why in conflicts:
        print(f"  ✗ {axis}: {why}")
    assert conflicts, "expected a density conflict between prod-db and test-dev"
    print("\n✅ self-test passed: prod-db ranks strictest AND is infeasible to co-locate with test-dev "
          "(→ re-place or declare a named `mixed` posture; never auto-compose).")
    return 0


def print_ranking(postures: dict) -> int:
    if not postures:
        print("no committed postures found"); return 0
    ranked = sorted(postures.values(), key=strictness_key, reverse=True)
    print("posture strictness ranking (strictest first — this is the intended priority order):")
    for i, p in enumerate(ranked, 1):
        print(f"  {i}. {p['posture']:28} key={strictness_key(p)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Shared-infrastructure governance: strictness ranking, feasibility, priority/config parity")
    ap.add_argument("--priority-parity", action="store_true", help="LIVE: assert the global policy order is strict-first")
    ap.add_argument("--config-parity", action="store_true", help="LIVE: assert policy capacity settings match the catalog (C2)")
    ap.add_argument("--self-test", action="store_true", help="exercise the feasibility check on committed data")
    args = ap.parse_args()
    postures = load_postures()
    if args.self_test:
        return self_test()
    if args.priority_parity:
        return priority_parity(postures)
    if args.config_parity:
        return config_parity(postures)
    return print_ranking(postures)


if __name__ == "__main__":
    sys.exit(main())
