#!/usr/bin/env python3
"""reconcile_policy.py — the idempotent WTPC policy controller (level-triggered desired-state).

Closes the one WTPC lifecycle layer that was still edge-triggered / manual: the posture POLICY. Every
other layer already converges to a stable NAME key — SMs (build.py, adopt-by-name + id-preserving PUT),
tags + groups (instantiate_posture.py), capacity (apply_policy_capacity.py), alerts (deploy_alerts.py).
Only the policy's EXISTENCE, PRIORITY order, and GROUP assignment were a manual UI clone plus a
check-only parity (governance.py). So a lab-redo that hand-recreated the policy minted a NEW id and
silently orphaned every binding that does not re-adopt-by-name — the referential fragility this controller removes.

Converges the policy layer to desired state from ANY starting point:
  * existence — ADOPT the policy named ``PCA - WTPC - Policy - <P>`` if it is live; CREATE it (clone the
                Default Policy via ``parentPolicy``) only under ``--create <P>`` — a deliberate bootstrap
                act, never a side effect of a routine reconcile (converge-by-default, create-on-opt-in).
  * priority  — converge the GLOBAL order so posture policies rank strict-first (governance.strictness_key),
                ahead of any non-posture ranked policy. ``PUT /api/policies/priorities`` fires only on
                drift, and only ever reorders the currently-ranked set — the unranked policies (27 on this
                lab) are never added or touched.
  * groups    — ENSURE each of a posture's three custom groups is assigned to its policy (the client's
                assign is server-side idempotent; the binding is not cheaply readable, so we
                ensure-by-assert and verify via the members' effective policy).

Emits ``policies.<P>.yaml`` (the instance id-record, like ``supermetrics.<P>.yaml`` / ``groups.<P>.yaml``).
Dry-run by default (mutating-op invariant); ``--execute`` applies; the post-condition (existence +
strict-first order) is re-read and asserted. Deep effective-policy parity stays ``validate_live.py --parity``.

Endpoints verified against the VCF Operations 9.1 public API specification:
  POST /api/policies            {name*, parentPolicy, description}   — create (clone Default)
  PUT  /api/policies/priorities {policyIds*: [ordered ids]}          — global priority order
  PUT  /api/policies/{id}/assign {groupIds*: [...]}                  — group assignment (NOT the older
                                                                        custom-groups path, which 404s on 9.1)

Usage (from deploy/vcf-ops-content/wtpc/):
  python reconcile_policy.py                                   # DRY-RUN: converge the LIVE posture policies
  python reconcile_policy.py --execute                         # apply the convergence
  python reconcile_policy.py --create test-dev-traditional --execute   # bootstrap a NEW posture policy
  python reconcile_policy.py --posture prod-latency-critical-db        # scope existence/groups to one posture
"""
from __future__ import annotations

import argparse
import os
import sys

import yaml
from lib._client import ops_client
from lib._groups import list_groups

import governance as gov   # load_postures(), strictness_key(), POLICY_PREFIX — the strictness ranker is the SoT

HERE = os.path.dirname(os.path.abspath(__file__))
GROUP_PREFIX = "PCA - WTPC - Group - "


# --- live reads (clean; /internal/policies carries id + name + priority + defaultPolicy) --------------
def live_policies(c: VcfOpsClient) -> list[dict]:
    return c.get("/internal/policies", params={"pageSize": 500}).json()["policy-summaries"]


def default_policy_id(summaries: list[dict]) -> str:
    d = next((p for p in summaries if p.get("defaultPolicy")), None)
    if not d:
        raise SystemExit("no Default Policy found live — cannot clone a posture policy from it")
    return d["id"]


def resolve_groups(c: VcfOpsClient, posture: str) -> list[dict]:
    """The posture's three custom groups, adopted LIVE by name (robust to the record-file naming drift).
    `includePolicy=true` populates each group's current `policy` binding — the truthful read; a
    plain GET omits it. All three groups carry the posture policy in the proven-working estate: the
    Host/Cluster SMs compute BECAUSE those objects have an effective policy that enables them (where an
    untiered object lands in two posture groups, priority resolves it strictest-resident-wins, not by
    refusing to bind; a tiered object is governed by its tier)."""
    pref = f"{GROUP_PREFIX}{posture} "
    groups = list_groups(c, include_policy=True)
    return [{"name": g["resourceKey"]["name"], "id": g["id"], "policy": g.get("policy") or g.get("policyId")}
            for g in groups if g.get("resourceKey", {}).get("name", "").startswith(pref)]


# --- existence: adopt-or-create -----------------------------------------------------------------------
def ensure_policy(c: VcfOpsClient, summaries: list[dict], posture: str, *,
                  create: bool, execute: bool) -> str | None:
    """Return the policy id for `posture`: adopt if live; create (clone Default) only when allowed."""
    name = gov.POLICY_PREFIX + posture
    live = next((p for p in summaries if p.get("name") == name), None)
    if live:
        print(f"  [{posture}] policy ADOPTED (exists)  id={live['id'][:8]}  prio={live.get('priority')}")
        return live["id"]
    if not create:
        print(f"  [{posture}] policy ABSENT — not created (converge-only). Re-run with --create {posture} to bootstrap.")
        return None
    parent = default_policy_id(summaries)
    if not execute:
        print(f"  [{posture}] DRY-RUN would CREATE policy {name!r} (clone Default {parent[:8]})")
        return None
    r = c.post("/api/policies", json={"name": name, "parentPolicy": parent,
                                      "description": "[pca-wtpc] posture policy — reconcile_policy.py"})
    r.raise_for_status()
    pid = r.json()["id"]
    print(f"  [{posture}] policy CREATED  id={pid[:8]}  (clone of Default {parent[:8]})")
    return pid


# --- groups: converge each posture group's policy binding to its policy -------------------------------
# Verified 9.1 endpoint (the VCF Operations 9.1 public API specification): PUT /api/policies/{id}/assign
# {groupIds:[...]}. (The client's assign_policy_to_custom_group POSTs /api/policies/{id}/custom-groups/{gid},
# which 404s on 9.1 — that path is absent from the 9.1 spec.) Level-triggered: read the live
# binding (includePolicy), PUT /assign only the drifted groups, idempotent when already bound.
def _label(name: str) -> str:
    return name.split("(")[-1].rstrip(")")


def ensure_group_assignment(c: VcfOpsClient, posture: str, pid: str, *, execute: bool) -> int:
    groups = resolve_groups(c, posture)
    if not groups:
        print(f"  [{posture}] no WTPC custom groups live yet — run instantiate_posture.py first (skipping assign)")
        return 0
    drift = [g for g in groups if g["policy"] != pid]
    for g in groups:
        state = "✓ bound" if g["policy"] == pid else f"DRIFT (policy={(g['policy'] or 'Default')[:8]})"
        print(f"  [{posture}] group {_label(g['name']):>8} ({g['id'][:8]}) {state}")
    if not drift:
        return len(groups)
    if not execute:
        print(f"  [{posture}] DRY-RUN would PUT /api/policies/{pid[:8]}/assign  "
              f"groupIds={[_label(g['name']) for g in drift]}")
        return len(groups)
    c.put(f"/api/policies/{pid}/assign", json={"groupIds": [g["id"] for g in drift]})
    print(f"  [{posture}] assigned {len(drift)} drifted group(s) → policy {pid[:8]}")
    return len(groups)


# --- priority: converge the global order to strict-first (preserve the non-posture ranked set) --------
def desired_priority_order(summaries: list[dict], postures: dict) -> tuple[list[str], list[str]]:
    """(desired_ranked_ids, current_ranked_ids). Posture policies with a committed source rank strict-first;
    every other currently-ranked policy keeps its relative order below them; unranked policies stay unranked."""
    ranked = sorted((p for p in summaries if p.get("priority") is not None),
                    key=lambda p: p["priority"])
    current = [p["id"] for p in ranked]

    def posture_of(p):
        nm = p.get("name", "")
        return nm[len(gov.POLICY_PREFIX):] if nm.startswith(gov.POLICY_PREFIX) else None

    # posture policies (ranked OR not) with a committed strictness source, strict-first
    posture_pols = [p for p in summaries if posture_of(p) in postures]
    posture_pols.sort(key=lambda p: gov.strictness_key(postures[posture_of(p)]), reverse=True)
    desired = [p["id"] for p in posture_pols]
    # then every currently-ranked policy not already placed (non-posture, or posture w/o committed source),
    # in current priority order
    for pid in current:
        if pid not in desired:
            desired.append(pid)
    return desired, current


def converge_priority(c: VcfOpsClient, summaries: list[dict], postures: dict, *, execute: bool) -> bool:
    desired, current = desired_priority_order(summaries, postures)
    id2name = {p["id"]: p.get("name", "?") for p in summaries}
    if desired == current:
        print("  priority: already strict-first — no reorder")
        return False
    print("  priority DRIFT — desired strict-first order differs from live:")
    for i, pid in enumerate(desired, 1):
        marker = "" if (i - 1 < len(current) and current[i - 1] == pid) else "  <-- moves"
        print(f"    {i:>2}. {id2name.get(pid, pid)[:52]:52}{marker}")
    if not execute:
        print("  DRY-RUN would PUT /api/policies/priorities (reorders only the currently-ranked set)")
        return True
    c.put("/api/policies/priorities", json={"policyIds": desired})
    print(f"  applied: PUT /api/policies/priorities ({len(desired)} ranked policies, posture strict-first)")
    return True


# --- id-record ---------------------------------------------------------------------------------------
def emit_record(posture: str, pid: str, groups: list[dict], priority) -> None:
    rec = {"policy": {"name": gov.POLICY_PREFIX + posture, "id": pid, "priority": priority,
                      "groups": [{"name": g["name"], "id": g["id"]} for g in groups]}}
    fn = os.path.join(HERE, f"policies.{posture}.yaml")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(f"# WTPC posture policy id — INSTANCE output record (resolved live; like supermetrics.{posture}.yaml).\n")
        f.write(f"# Regenerate: python reconcile_policy.py --posture {posture} --execute   (adopt-or-create)\n")
        yaml.safe_dump(rec, f, sort_keys=False, default_flow_style=False)
    print(f"  emitted policies.{posture}.yaml")


def main() -> int:
    ap = argparse.ArgumentParser(description="Idempotent WTPC policy controller (adopt-or-create + converge)")
    ap.add_argument("--posture", help="scope existence/groups to one posture (priority is always global)")
    ap.add_argument("--create", metavar="POSTURE", action="append", default=[],
                    help="permit CREATE (clone Default) for this posture if absent; repeatable")
    ap.add_argument("--execute", action="store_true", help="apply mutations (default: dry-run)")
    args = ap.parse_args()

    postures = gov.load_postures()
    with ops_client() as c:
        summaries = live_policies(c)
        mode = "EXECUTE" if args.execute else "DRY-RUN"
        print(f"reconcile_policy · {mode}  (converge-by-default; create only for {args.create or '[]'})\n")

        # which postures to reconcile existence/groups for: the LIVE posture policies, plus any --create,
        # optionally narrowed by --posture. (Priority always spans the full live posture set.)
        live_names = {p["name"][len(gov.POLICY_PREFIX):] for p in summaries
                      if p.get("name", "").startswith(gov.POLICY_PREFIX)}
        targets = sorted((live_names | set(args.create)) if not args.posture else {args.posture})
        unknown = [p for p in targets if p not in postures]
        if unknown:
            print(f"⚠ no committed posture source for {unknown} — will adopt/priority but not rank by strictness")

        print("1) existence (adopt-or-create) + group assignment")
        record: dict[str, tuple] = {}
        for p in targets:
            pid = ensure_policy(c, summaries, p, create=(p in args.create), execute=args.execute)
            if pid:
                groups = resolve_groups(c, p)
                ensure_group_assignment(c, p, pid, execute=args.execute)
                prio = next((s.get("priority") for s in summaries if s["id"] == pid), None)
                record[p] = (pid, groups, prio)

        if args.execute and args.create:      # a fresh create shifts the live set — re-read before ranking
            summaries = live_policies(c)

        print("\n2) priority order (global; strict-first)")
        converge_priority(c, summaries, postures, execute=args.execute)

        if args.execute:
            print("\n3) verify post-condition")
            after = live_policies(c)
            for p in targets:
                ok = any(s.get("name") == gov.POLICY_PREFIX + p for s in after)
                print(f"  [{p}] policy present: {'✅' if ok else '❌ MISSING'}")
            rc = gov.priority_parity(postures)   # asserts strict-first live; prints the ranked table
            for p, (pid, groups, _) in record.items():
                prio = next((s.get("priority") for s in after if s["id"] == pid), None)
                emit_record(p, pid, groups, prio)
            print("\nDone. Deep effective-policy parity: python validate_live.py --parity")
            return rc

        print("\nDry-run complete. Re-run with --execute to converge. "
              "Bootstrap a new posture: --create <posture> --execute.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
