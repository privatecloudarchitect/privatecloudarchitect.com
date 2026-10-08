#!/usr/bin/env python3
"""reconcile_policy.py — the idempotent WTPC policy controller (level-triggered desired-state).

Closes the one WTPC lifecycle layer that was still edge-triggered / manual: the posture POLICY. Every
other layer already converges to a stable NAME key — SMs (build.py, adopt-by-name + id-preserving PUT),
tags + groups (instantiate_posture.py), capacity (apply_policy_capacity.py), alerts (deploy_alerts.py).
Only the policy's EXISTENCE, PRIORITY order, and GROUP assignment were a manual UI clone plus a
check-only parity (governance.py). So a lab-redo that hand-recreated the policy minted a NEW id and
silently orphaned every binding that does not re-adopt-by-name — the referential fragility this controller removes.

Converges the policy layer to desired state from ANY starting point:
  * existence: ADOPT the posture policy (``lib._names.posture_policy(P)``, either spelling) if it is
                live; CREATE it (clone the
                Default Policy via ``parentPolicy``) only under ``--create <P>`` — a deliberate bootstrap
                act, never a side effect of a routine reconcile (converge-by-default, create-on-opt-in).
  * priority  — rank the posture policies strict-first (governance.strictness_key) inside the positions
                they already hold in the global order, leaving every other team's policy where it is
                (lib/_priority.py). ``--rank-above-foreign`` instead places them ahead of every other ranked
                policy, an explicit decision for an estate whose other policies take posture members (the
                parity gate names them). ``PUT /api/policies/priorities`` fires only on drift, and only ever
                reorders the currently-ranked set; unranked policies are never added or touched.
  * groups    — ENSURE the posture policy governs its VMs group, and its Hosts and Clusters groups only
                when no tier policy is live (hardware takes its tier); release it where it must not.
                Each binding is read with includePolicy=true before and after the write.

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
from lib._names import is_posture_group, is_posture_policy, is_tier_policy, posture_policy, same, scope_of
from lib._priority import above_foreign, within_own_slots
from lib._groups import list_groups

import governance as gov   # load_postures(), strictness_key(); the strictness ranker is the SoT

HERE = os.path.dirname(os.path.abspath(__file__))


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
    plain GET omits it. Which of the three groups the posture policy should govern is
    ensure_group_assignment's rule: the VMs group always, the Hosts and Clusters groups only on an estate
    with no tier policies (hardware is governed by its tier)."""
    groups = list_groups(c, include_policy=True)
    return [{"name": g["resourceKey"]["name"], "id": g["id"], "policy": g.get("policy") or g.get("policyId")}
            for g in groups
            if is_posture_group(g.get("resourceKey", {}).get("name", ""))
            and scope_of(g["resourceKey"]["name"]) == posture]


# --- existence: adopt-or-create -----------------------------------------------------------------------
def ensure_policy(c: VcfOpsClient, summaries: list[dict], posture: str, *,
                  create: bool, execute: bool) -> str | None:
    """Return the policy id for `posture`: adopt if live; create (clone Default) only when allowed."""
    name = posture_policy(posture)
    live = next((p for p in summaries if same(p.get("name", ""), name)), None)
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
    """Bind the posture policy where it governs, and release it where it must not.

    The posture's VMs group always carries the posture policy. Its Hosts and Clusters groups carry it only on
    an estate with no tier policies. Once tier policies are live, hardware is governed by its tier (the tier model): a
    posture's hardware groups are derived from where its VMs run, so a posture binding there would pull
    shared hosts and clusters out of their tier and under one workload's posture, because posture policies
    rank above tier policies. reconcile_infra_groups.py leaves those groups unbound when it rewrites them;
    this releases a binding it could not reach (a posture with no VMs, which that reconciler refuses).
    A hardware group bound to some other policy is reported and left alone.
    """
    groups = resolve_groups(c, posture)
    if not groups:
        print(f"  [{posture}] no WTPC custom groups live yet — run instantiate_posture.py first (skipping assign)")
        return 0
    tier_model = any(is_tier_policy(p.get("name", "")) for p in live_policies(c))
    governs = {g["id"]: _label(g["name"]) == "VMs" or not tier_model for g in groups}
    bind = [g for g in groups if governs[g["id"]] and g["policy"] != pid]
    release = [g for g in groups if not governs[g["id"]] and g["policy"] == pid]
    for g in groups:
        if governs[g["id"]]:
            state = "✓ bound" if g["policy"] == pid else f"DRIFT (policy={(g['policy'] or 'Default')[:8]})"
        elif g["policy"] == pid:
            state = "DRIFT (bound to the posture; hardware takes its tier)"
        else:
            state = "✓ not the posture's (hardware takes its tier)" + (f", bound to {g['policy'][:8]}" if g["policy"] else "")
        print(f"  [{posture}] group {_label(g['name']):>8} ({g['id'][:8]}) {state}")
    if not bind and not release:
        return len(groups)
    if not execute:
        if bind:
            print(f"  [{posture}] DRY-RUN would PUT /api/policies/{pid[:8]}/assign  groupIds={[_label(g['name']) for g in bind]}")
        if release:
            print(f"  [{posture}] DRY-RUN would PUT /api/policies/{pid[:8]}/unassign  groupIds={[_label(g['name']) for g in release]}")
        return len(groups)
    if bind:
        c.put(f"/api/policies/{pid}/assign", json={"groupIds": [g["id"] for g in bind]})
        print(f"  [{posture}] assigned {len(bind)} drifted group(s) → policy {pid[:8]}")
    if release:
        c.put(f"/api/policies/{pid}/unassign", json={"groupIds": [g["id"] for g in release]})
        print(f"  [{posture}] released {len(release)} hardware group(s) from policy {pid[:8]} (hardware takes its tier)")
    after = {g["id"]: g["policy"] for g in resolve_groups(c, posture)}
    wrong = [_label(g["name"]) for g in groups if (after.get(g["id"]) == pid) != governs[g["id"]]]
    if wrong:
        raise SystemExit(f"  [{posture}] read-back: {wrong} not as intended")
    return len(groups)


# --- priority: converge the global order to strict-first (preserve the non-posture ranked set) --------
def desired_priority_order(summaries: list[dict], postures: dict, *, above_foreign_policies: bool = False
                           ) -> tuple[list[str], list[str]]:
    """(desired_ranked_ids, current_ranked_ids). Posture policies with a committed source rank strict-first,
    inside the positions they already hold (every other policy stays where it is), or, with
    `above_foreign_policies`, ahead of every other ranked policy. Unranked policies stay unranked."""
    ranked = sorted((p for p in summaries if p.get("priority") is not None),
                    key=lambda p: p["priority"])
    current = [p["id"] for p in ranked]

    def posture_of(p):
        nm = p.get("name", "")
        return scope_of(nm) if is_posture_policy(nm) else None

    # posture policies (ranked OR not) with a committed strictness source, strict-first
    posture_pols = [p for p in summaries if posture_of(p) in postures]
    posture_pols.sort(key=lambda p: gov.strictness_key(postures[posture_of(p)]), reverse=True)
    ours = [p["id"] for p in posture_pols]
    return (above_foreign(current, ours) if above_foreign_policies else within_own_slots(current, ours)), current


def converge_priority(c: VcfOpsClient, summaries: list[dict], postures: dict, *, execute: bool,
                      above_foreign_policies: bool = False) -> bool:
    desired, current = desired_priority_order(summaries, postures, above_foreign_policies=above_foreign_policies)
    id2name = {p["id"]: p.get("name", "?") for p in summaries}
    if desired == current:
        print("  priority: posture policies already strict-first"
              + (" ahead of every other policy" if above_foreign_policies else " in the positions they hold; no other policy moves")
              + " — no reorder")
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
def emit_record(posture: str, pid: str, groups: list[dict], priority, live_name: str | None = None) -> None:
    rec = {"policy": {"name": live_name or posture_policy(posture), "id": pid, "priority": priority,
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
    ap.add_argument("--rank-above-foreign", action="store_true",
                    help="rank the posture policies ahead of every other ranked policy (default: reorder only "
                         "inside the positions they hold, leaving other teams' policies where they are)")
    args = ap.parse_args()

    postures = gov.load_postures()
    with ops_client() as c:
        summaries = live_policies(c)
        mode = "EXECUTE" if args.execute else "DRY-RUN"
        print(f"reconcile_policy · {mode}  (converge-by-default; create only for {args.create or '[]'})\n")

        # which postures to reconcile existence/groups for: the LIVE posture policies, plus any --create,
        # optionally narrowed by --posture. (Priority always spans the full live posture set.)
        live_names = {scope_of(p["name"]) for p in summaries if is_posture_policy(p.get("name", ""))}
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
        converge_priority(c, summaries, postures, execute=args.execute, above_foreign_policies=args.rank_above_foreign)

        if args.execute:
            print("\n3) verify post-condition")
            after = live_policies(c)
            for p in targets:
                ok = any(same(s.get("name", ""), posture_policy(p)) for s in after)
                print(f"  [{p}] policy present: {'✅' if ok else '❌ MISSING'}")
            rc = gov.priority_parity(postures)   # asserts strict-first live; prints the ranked table
            for p, (pid, groups, _) in record.items():
                prio = next((s.get("priority") for s in after if s["id"] == pid), None)
                live_name = next((s.get("name") for s in after if s["id"] == pid), None)
                emit_record(p, pid, groups, prio, live_name)
            print("\nDone. Deep effective-policy parity: python validate_live.py --parity")
            return rc

        print("\nDry-run complete. Re-run with --execute to converge. "
              "Bootstrap a new posture: --create <posture> --execute.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
