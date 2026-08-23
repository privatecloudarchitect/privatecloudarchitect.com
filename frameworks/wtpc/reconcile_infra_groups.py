#!/usr/bin/env python3
"""WTPC posture infra-membership reconciler - the "follows the workload" model.

The VMs group is tag-declarative (its members auto-follow VCFA/orchestrator deploys that carry the
posture tags). The Host and Cluster groups are DERIVED: their members are exactly the hosts running,
and the clusters hosting, the posture VMs.

WHY a reconciler and not a declarative rule: vROps custom-group relationship rules match the far
object by NAME, never by tag or by another group's membership (VERIFIED - 9.1 spec relation enum
PARENT|CHILD|ANCESTOR|DESCENDANT with a name/compareOperator far match; and the only two live groups
using relationship rules both anchor on a named container, "DESCENDANT of vSphere World" etc.). The
rule engine cannot see the workload tag across the host<->VM edge, and the VMs custom group sits
BESIDE the host as a co-parent of the VM (not above it), so there is no downward path from the group
to the hosts. "Infra running the tagged workload" is therefore not expressible declaratively; this
reconciler computes it by walking each VMs-group member up the vSphere hierarchy
(VM --PARENT--> HostSystem --PARENT--> ClusterComputeResource) and writing the result as the Host
and Cluster groups' includedResources, with the drift-prone tag rules dropped.

Day-10 property: deploy a posture VM onto new hardware -> it is tagged (automatable) -> it joins the
VMs group (~13 min re-resolution) -> the next reconciler run pulls its host + cluster in. No operator
re-tagging of infrastructure for posture membership (the hardware's tier tag is a separate, tooling-set step).

Idempotent: reads current includedResources, computes the desired set, and PUTs only on a diff.
Safe: refuses to blank a populated infra group when the VMs group resolves to zero members (a likely
transient re-resolution) unless --force is given. Dry-run by default (mutating-op invariant).

HARDWARE GOVERNANCE DEFAULT: the derived Host/Cluster MEMBERSHIP is always maintained (it feeds
--analyze), but under the tier model the posture policy is NOT bound to the infra groups — HARDWARE
IS GOVERNED BY ITS TIER. So when tier policies are live this run WIPES the posture policy off the infra
groups (they fall to their tier); a pre-tier estate (no tier policies), or --posture-governs-hardware,
keeps the legacy posture binding. This is the DEFAULT so a routine reconcile never silently re-binds a
tier-governed estate back to its posture.

Usage:
  python reconcile_infra_groups.py             # DRY-RUN: membership diff + the governance mode, write nothing
  python reconcile_infra_groups.py --execute   # apply (PUT the Host + Cluster groups)
  python reconcile_infra_groups.py --posture <name>            # default: prod-latency-critical-db
  python reconcile_infra_groups.py --posture-governs-hardware  # LEGACY: bind the posture policy (pre-tier)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import governance  # sibling module (same dir on sys.path): strictness + feasibility
from lib import _taxonomy  # concept -> runtime category-name resolver (posture membership rule)
from lib._client import ops_client
from lib._groups import GROUPS_ENDPOINT, list_groups

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, ".reconcile-state.json")   # runtime dwell state (gitignored)
MEM_RESERVATION_PROP = "config|memoryAllocation|reservation"   # MB; verified live
DEFAULT_DWELL_HOURS = 24.0                                  # doctrine L5: no tier change on <24h residency


def group_name(posture: str, tier: str) -> str:
    return f"PCA - WTPC - Group - {posture} ({tier})"


def resolve_groups(c: VcfOpsClient, posture: str) -> dict:
    """Map tier -> full custom-group payload for the three posture groups (by name). includePolicy so
    the payload carries any assigned policy - a group PUT that omits it WIPES the assignment."""
    want = {group_name(posture, t): t for t in ("VMs", "Hosts", "Clusters")}
    found = {}
    for g in list_groups(c, include_policy=True):
        name = g.get("resourceKey", {}).get("name")
        if name in want:
            found[want[name]] = g
    missing = [group_name(posture, t) for t in ("VMs", "Hosts", "Clusters") if t not in found]
    if missing:
        raise SystemExit(f"group(s) not found - run step-3 instantiation first: {missing}")
    return found


def resolve_posture_policy_id(c: VcfOpsClient, posture: str) -> str | None:
    """Id of the posture's WTPC policy (PCA - WTPC - Policy - <posture>), or None if not instantiated."""
    want = f"PCA - WTPC - Policy - {posture}"
    for p in c.get("/api/policies", params={"_no_links": "true", "pageSize": 500}).json().get("policySummaries", []):
        if p.get("name") == want:
            return p["id"]
    return None


def vms_group_members(c: VcfOpsClient, group_id: str) -> list[str]:
    body = c.get(f"{GROUPS_ENDPOINT}/{group_id}/members", params={"_no_links": "true"}).json()
    return [r["identifier"] for r in body.get("resourceList", []) if r.get("identifier")]


def parents_of_kind(c: VcfOpsClient, rid: str, kind: str) -> list[tuple[str, str]]:
    """Immediate PARENT resources of `rid` of the given resourceKindKey -> [(id, name)]."""
    body = c.get(f"/api/resources/{rid}/relationships",
                 params={"relationshipType": "PARENT", "_no_links": "true"}).json()
    out = []
    for r in body.get("resourceList", []):
        rk = r.get("resourceKey", {})
        if rk.get("resourceKindKey") == kind:
            out.append((r["identifier"], rk.get("name")))
    return out


def derive_infra(c: VcfOpsClient, vm_ids: list[str]) -> tuple[dict, dict, list[str]]:
    """Walk VM --PARENT--> Host --PARENT--> Cluster. Returns (hosts, clusters, orphan_vm_ids)
    where hosts/clusters are {id: name}."""
    hosts: dict[str, str] = {}
    clusters: dict[str, str] = {}
    orphans: list[str] = []
    for vm in vm_ids:
        vm_hosts = parents_of_kind(c, vm, "HostSystem")
        if not vm_hosts:
            orphans.append(vm)
            continue
        for hid, hname in vm_hosts:
            hosts[hid] = hname
            for cid, cname in parents_of_kind(c, hid, "ClusterComputeResource"):
                clusters[cid] = cname
    return hosts, clusters, orphans


def members_with_names(c: VcfOpsClient, group_id: str) -> list[tuple[str, str]]:
    body = c.get(f"{GROUPS_ENDPOINT}/{group_id}/members", params={"_no_links": "true"}).json()
    return [(r["identifier"], r.get("resourceKey", {}).get("name", r["identifier"]))
            for r in body.get("resourceList", []) if r.get("identifier")]


def children_of_kind(c: VcfOpsClient, rid: str, kind: str) -> list[tuple[str, str]]:
    """Immediate CHILD resources of `rid` of the given resourceKindKey -> [(id, name)]."""
    body = c.get(f"/api/resources/{rid}/relationships",
                 params={"relationshipType": "CHILD", "_no_links": "true"}).json()
    return [(r["identifier"], r.get("resourceKey", {}).get("name"))
            for r in body.get("resourceList", []) if r.get("resourceKey", {}).get("resourceKindKey") == kind]


def mem_reservation_mb(c: VcfOpsClient, vm_id: str):
    """VM memory reservation in MB (0.0 = none), or None if the property is absent."""
    props = c.get(f"/api/resources/{vm_id}/properties", params={"_no_links": "true"}).json()
    for p in props.get("property", []):
        if p.get("name") == MEM_RESERVATION_PROP:
            return governance._num(p.get("value"))
    return None


# --- hysteresis: hold a departed resource for a dwell window so DRS vMotion can't thrash the tier ----

def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def apply_hysteresis(group_id, current_included, desired_ids, state, now, dwell_hours):
    """Effective set = desired ∪ {recently-departed within the dwell window}. Stamps desired as seen-now,
    ages out entries past the window. Returns (effective_ids, held_ids)."""
    grp = state.setdefault(group_id, {})
    now_iso = now.isoformat()
    for r in desired_ids:
        grp[r] = now_iso
    effective, held = set(desired_ids), []
    dwell = timedelta(hours=dwell_hours)
    for r in current_included:
        if r in desired_ids:
            continue
        last = grp.get(r)
        if last is None:
            grp[r] = last = now_iso   # first notice of departure (or lost state) -> start the clock here
        try:
            recent = now - datetime.fromisoformat(last) < dwell   # dwell=0 => never recent => drop now
        except ValueError:
            recent = False                                        # unparseable -> allow the drop
        if recent:
            effective.add(r); held.append(r)
        else:
            grp.pop(r, None)   # past the dwell window -> drop
    for r in list(grp):    # prune stale bookkeeping
        if r in effective:
            continue
        try:
            if now - datetime.fromisoformat(grp[r]) >= timedelta(hours=dwell_hours):
                del grp[r]
        except (ValueError, TypeError):
            del grp[r]
    return effective, held


def plan_group(group: dict, desired_ids: set[str], policy_id: str | None = None,
               empty_rules: list | None = None, retire_policy: bool = False) -> dict | None:
    """Return an updated custom-group payload if a change is needed, else None (idempotent no-op).
    Desired membership = includedResources == desired_ids, with tag/other rules dropped.

    EMPTY case (`desired_ids` empty — only reachable under --force): a group with NO rules AND NO members
    is INVALID — vROps rejects the PUT with 400. So when the desired set is empty and `empty_rules`
    is supplied, the group is made RULE-based instead (restore the posture tag rule, which resolves to zero
    once no host/cluster carries the tags) — a valid, correctly-empty posture group. Without `empty_rules`
    the legacy behaviour (blank to includedResources=[]) is kept for callers that never blank.

    Policy: a group PUT that omits the `policy` field WIPES the assignment. If `policy_id` is
    given, the group is made to carry it — self-healing, since a pre-fix reconcile PUT could have wiped
    it and left the infra members shadowed by Default Policy; if not given, any existing assignment is
    preserved unchanged. A policy-only delta (membership already correct) still triggers the PUT."""
    md = group.get("membershipDefinition", {}) or {}
    current = set(md.get("includedResources") or [])
    cur_rules = md.get("rules") or []
    cur_pol = group.get("policy") or group.get("policyId")
    # retire_policy (P2/S5): omit the policy so the group PUT WIPES the posture binding and the
    # hardware falls to its TIER policy — hardware is governed by its tier, not by a workload posture.
    want_pol = None if retire_policy else (policy_id or cur_pol)   # ensure the posture policy, else preserve/retire
    restore_rule = not desired_ids and empty_rules is not None   # the --force empty case → rule, not blank
    want_included = [] if restore_rule else sorted(desired_ids)
    want_rules = empty_rules if restore_rule else []      # rule-based-empty, else includedResources-only
    if current == set(want_included) and cur_rules == want_rules and want_pol == cur_pol:
        return None
    new_md = dict(md)
    new_md["includedResources"] = want_included
    new_md["rules"] = want_rules   # drop the drift-prone tag rule EXCEPT when restoring it to a valid-empty group
    payload = {k: group[k] for k in ("id", "resourceKey", "autoResolveMembership") if k in group}
    if want_pol:
        payload["policy"] = want_pol
    payload["membershipDefinition"] = new_md
    return payload


def _posture_tag_rule(posture_doc: dict, resource_kind: str) -> list:
    """The posture's membership tag rule (env ∧ workload ∧ sla) as a custom-group `rules` payload, targeting
    `resource_kind` — a valid rule that resolves to ZERO hosts/clusters (nothing infra carries these tags),
    so it is the correct 'empty posture infra group' membership."""
    pr = _taxonomy.posture_runtime()  # concept -> live runtime category name (workload -> identity.function)
    conds = [{"category": pr.get(cat, cat), "compareOperator": "EQ", "stringValue": val}
             for cat, val in (posture_doc.get("membership") or {}).items()]
    return [{"resourceKindKey": {"resourceKind": resource_kind, "adapterKind": "VMWARE"},
             "statConditionRules": [], "propertyConditionRules": [], "resourceNameConditionRules": [],
             "relationshipConditionRules": [], "resourceTagConditionRules": conds}]


def analyze(c: VcfOpsClient) -> int:
    """Governance analysis (doctrine L5): per-cluster posture occupancy, mixed-posture feasibility, the
    dilution ('one VM poisons the cluster') signal, and the reservation audit. Read-only."""
    postures = governance.load_postures()
    all_groups = list_groups(c)
    gname_to_id = {g.get("resourceKey", {}).get("name"): g["id"] for g in all_groups}
    live = {}   # posture -> [(vmid, vmname)]
    for pname in postures:
        gid = gname_to_id.get(group_name(pname, "VMs"))
        if gid:
            live[pname] = members_with_names(c, gid)
    if not live:
        print("no instantiated posture VMs groups found"); return 0

    cluster_occ = {}   # cid -> {"name":.., "byp": {posture: [vmname]}}
    for pname, members in live.items():
        for vmid, vmname in members:
            for hid, _ in parents_of_kind(c, vmid, "HostSystem"):
                for cid, cname in parents_of_kind(c, hid, "ClusterComputeResource"):
                    occ = cluster_occ.setdefault(cid, {"name": cname, "byp": {}})
                    occ["byp"].setdefault(pname, []).append(vmname)

    print(f"governance analysis · {len(live)} instantiated posture(s), {len(cluster_occ)} cluster(s) in scope")
    for cid, info in sorted(cluster_occ.items(), key=lambda kv: kv[1]["name"]):
        total = sum(len(children_of_kind(c, hid, "VirtualMachine"))
                    for hid, _ in children_of_kind(c, cid, "HostSystem"))
        residents = list(info["byp"])
        strictest = max(residents, key=lambda p: governance.strictness_key(postures[p]))
        postured = sum(len(v) for v in info["byp"].values())
        print(f"\nCLUSTER {info['name']}  ({postured} postured of {total} VMs total)")
        for p, vms in info["byp"].items():
            gov = " ← GOVERNS (strictest resident)" if p == strictest and len(residents) > 1 else ""
            print(f"   {p}: {len(vms)} {vms}{gov}")
        if len(residents) > 1:
            confs = []
            for i in range(len(residents)):
                for j in range(i + 1, len(residents)):
                    confs += governance.envelope_conflicts(postures[residents[i]], postures[residents[j]])
            if confs:
                print(f"   ❌ MIXED-POSTURE CONFLICT on {sorted({a for a, _ in confs})} — re-place, or declare a "
                      f"named `mixed` posture (never auto-compose). Governing tier = {strictest}.")
            else:
                print(f"   ✓ nested (no conflict) — governed by {strictest} (strictest-resident-wins).")
        elif total and postured / total < 0.25:
            print(f"   ⚠ DILUTION: {postured}/{total} VMs drive {strictest} governance here. If a misplacement, "
                  f"quarantine the stray VM (fit finding) — do NOT convert the cluster.")

    print("\nreservation audit (strict postures require per-VM reservation isolation — doctrine L3):")
    flagged = 0
    for pname, members in live.items():
        env = postures[pname].get("envelope", {}) or {}
        needs = (env.get("performance", {}).get("protection_coverage") == "required"
                 or governance._num(env.get("capacity", {}).get("mem_overcommit", {}).get("target")) == 1.0)
        if not needs:
            continue
        for vmid, vmname in members:
            r = mem_reservation_mb(c, vmid)
            if r is not None and r <= 0:
                print(f"   ✗ {vmname} ({pname}): mem reservation = {r:g} MB — the 1.0 envelope is UNPROTECTED "
                      f"on shared metal (set a full memory reservation, or its isolation is a promise only)")
                flagged += 1
    if not flagged:
        print("   ✓ all strict-posture VMs carry a memory reservation")
    return 0


def hysteresis_self_test() -> int:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    state = {}
    eff, held = apply_hysteresis("g", {"A", "B", "C"}, {"A", "B"}, state, now, 24.0)
    assert eff == {"A", "B", "C"} and held == ["C"], (eff, held)          # C departed but held within dwell
    eff, held = apply_hysteresis("g", {"A", "B", "C"}, {"A", "B"}, state, now + timedelta(hours=25), 24.0)
    assert eff == {"A", "B"} and not held, (eff, held)                    # 25h later -> C dropped
    assert "C" not in state["g"]                                          # bookkeeping pruned
    # dwell=0 must drop a departed member immediately, even on first notice (no prior stamp)
    eff, held = apply_hysteresis("g2", {"A", "B", "C"}, {"A", "B"}, {}, now, 0.0)
    assert eff == {"A", "B"} and not held, (eff, held)
    print("✅ hysteresis self-test: held for the dwell window then dropped; dwell=0 drops immediately.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile WTPC Host+Cluster group membership from the VMs group's ancestry")
    ap.add_argument("--posture", default="prod-latency-critical-db")
    ap.add_argument("--execute", action="store_true", help="apply the PUT (default: dry-run)")
    ap.add_argument("--force", action="store_true",
                    help="when the VMs group is empty, reconcile the infra groups to a valid rule-restored "
                         "zero-member state (the posture tag rule, which matches nothing — NOT an "
                         "invalid blank that vROps 400s)")
    ap.add_argument("--analyze", action="store_true", help="read-only governance pass (occupancy, feasibility, reservations)")
    ap.add_argument("--posture-governs-hardware", action="store_true",
                    help="LEGACY opt-out: bind the posture policy to the Host+Cluster groups (posture governs "
                         "hardware). The DEFAULT under the tier model is the opposite — HARDWARE IS "
                         "GOVERNED BY ITS TIER, so the posture policy is NOT bound to infra groups; they fall "
                         "to their tier. A pre-tier estate (no tier policies live) uses this automatically.")
    ap.add_argument("--dwell-hours", type=float, default=DEFAULT_DWELL_HOURS,
                    help=f"hysteresis window before a departed resource is dropped (default {DEFAULT_DWELL_HOURS})")
    ap.add_argument("--self-test", action="store_true", help="exercise the hysteresis logic offline (no API)")
    args = ap.parse_args()

    if args.self_test:
        return hysteresis_self_test()

    with ops_client() as c:
        if args.analyze:
            return analyze(c)

        groups = resolve_groups(c, args.posture)
        vm_ids = vms_group_members(c, groups["VMs"]["id"])
        print(f"VMs group: {len(vm_ids)} member(s) (tag-declarative)")
        hosts, clusters, orphans = derive_infra(c, vm_ids)
        print(f"derived from ancestry: {len(hosts)} host(s), {len(clusters)} cluster(s)"
              + (f"; {len(orphans)} VM(s) with no host parent (skipped)" if orphans else ""))

        if not vm_ids and not args.force:
            print("\nREFUSING to reconcile: the VMs group is empty (likely a transient re-resolution).")
            print("Re-run once the group repopulates, or pass --force to blank the infra groups deliberately.")
            return 2

        state = _load_state()
        now = datetime.now(timezone.utc)
        policy_id = resolve_posture_policy_id(c, args.posture)
        if policy_id is None:
            print(f"⚠ posture policy 'PCA - WTPC - Policy - {args.posture}' not found — infra groups keep "
                  "their current policy (run step-5 policy instantiation first)")
        posture_doc = governance.load_postures().get(args.posture, {})   # for the empty-blank rule-restore
        # Hardware = TIER by default : if tier policies are live, DON'T bind the posture policy to the
        # infra groups — the hardware is governed by its tier. Only a pre-tier estate (no tier policies) or an
        # explicit --posture-governs-hardware keeps the legacy binding (else hardware would strand on Default).
        tier_model_active = any(p.get("name", "").startswith("PCA - WTPC - Tier - ")
                                for p in c.get("/api/policies", params={"pageSize": 500, "_no_links": "true"}).json()["policySummaries"])
        retire_hardware = tier_model_active and not args.posture_governs_hardware
        print("hardware governance: " + ("TIER (posture policy not bound to infra groups; untiered hardware "
              "falls to Default)" if retire_hardware else
              "POSTURE (legacy binding)" + ("" if tier_model_active else " — no tier policies live")))
        targets = [("Hosts", hosts, "HostSystem"), ("Clusters", clusters, "ClusterComputeResource")]
        planned = []
        for tier, desired, kind in targets:
            g = groups[tier]
            current = set((g.get("membershipDefinition", {}) or {}).get("includedResources") or [])
            desired_ids = set(desired)
            eff, held = apply_hysteresis(g["id"], current, desired_ids, state, now, args.dwell_hours)
            adds = sorted(desired_ids - current)
            drops = sorted(current - eff)
            print(f"\n{tier} group  [{g['id']}]  keep={len(current & eff)} add={len(adds)} drop={len(drops)} held={len(held)}")
            for i in adds:
                print(f"      + {desired[i]}")
            for i in drops:
                print(f"      - {i}")
            for i in held:
                print(f"      ~ {i}  (departed; held under {args.dwell_hours:g}h dwell)")
            retire = retire_hardware                          # hardware = tier; both Host + Cluster
            cur_pol = g.get("policy") or g.get("policyId")
            if retire and cur_pol:
                print(f"      policy: RETIRE (wipe {args.posture} → {tier.lower()} governed by their TIER)")
            elif policy_id and cur_pol != policy_id and not retire:
                print(f"      policy: ASSIGN {args.posture} (was {'none' if not cur_pol else 'another policy'}  repair)")
            payload = plan_group(g, eff, policy_id=policy_id,
                                 empty_rules=_posture_tag_rule(posture_doc, kind), retire_policy=retire)
            if not eff and payload is not None:
                print(f"      (empty → rule-restored to a valid zero-member group, not blanked)")
            if payload is None:
                print("    -> already in sync (no change)")
            else:
                planned.append((tier, payload))

        if not planned:
            if args.execute:                # persist dwell bookkeeping only on a real run, never on a preview
                _save_state(state)
            print("\nAll infra groups already reconciled. Nothing to do.")
            return 0

        if not args.execute:
            print(f"\nDRY-RUN: {len(planned)} group(s) would be updated. Re-run with --execute to apply.")
            return 0                         # dry-run is side-effect-free: no PUT, no state save

        for tier, payload in planned:
            c.put(GROUPS_ENDPOINT, json=payload)
            md = payload["membershipDefinition"]
            n = len(md["includedResources"])
            note = "rule restored (valid empty)" if md.get("rules") else "rules dropped"
            pol_note = "" if "policy" in payload else ", policy RETIRED"
            print(f"  APPLIED {tier}: includedResources={n}, {note}{pol_note}")
        _save_state(state)
        print("\nReconciled. (Custom-group re-resolution is asynchronous - allow a few minutes for the UI to reflect it.)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
