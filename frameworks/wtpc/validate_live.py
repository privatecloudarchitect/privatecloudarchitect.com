#!/usr/bin/env python3
"""WTPC effective-policy PARITY check (read-only) — every posture-group member must be governed by the policy
that should govern it: the posture policy for its VMs and, on a tiered estate, each host's and cluster's tier
policy. This is the gate apply.py runs per posture.

RETIRED (Model-A migration): this file used to ALSO define tag categories + assign posture tags via the
VCF Ops centralized Tag Management plane (`/internal/tagmanagement/*`). Both moved to purpose-built tools
because the Ops-to-vCenter projection of new categories proved unreliable:
  • category DEFINITION -> ensure_tag_definitions.py  (native, fleet-wide)
  • tag ASSIGNMENT       -> reconcile_posture_membership.py  (the vCenter tag-association plane)
Only the read-only parity gate remains here (plus the shared `Ctx` dry-run/execute helper the reconcilers
import). The F-TAGLOGIC + the catalog SM-scoping proofs it once ran are subsumed by the working Model-A estate.

A member resolving to another policy is SHADOWED by precedence — a broader policy ranked above the WTPC
policy wins entirely, silently breaking SM compute AND alert firing on that member. This read-only check
NAMES the shadowing policy so the priority order can be corrected deliberately.

Usage:
  python validate_live.py --posture <name> [--representative <vm-id>] [--nonmember <vm-id>]
"""
from __future__ import annotations

import argparse
import sys

from lib._client import ops_client
from lib._names import is_tier_group, is_tier_policy, posture_group, posture_policy, same
from lib._groups import list_groups


class Posture:
    """The posture identity the parity check needs: its name (→ group names) + its policy name."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.policy = posture_policy(name)


class Ctx:
    """Dry-run/execute helper shared by the WTPC reconcilers (`from validate_live import Ctx`). `act` prints
    the intended mutation and either runs it (execute) or reports it (dry-run)."""

    def __init__(self, client: VcfOpsClient, execute: bool, posture: "Posture | None" = None) -> None:
        self.c = client
        self.execute = execute
        self.p = posture

    def act(self, desc: str, fn):
        if not self.execute:
            print(f"  DRY-RUN would: {desc}")
            return None
        print(f"  {desc}")
        return fn()


def resolve_group_id(c, name: str) -> str:
    for g in list_groups(c, include_policy=False):
        if same(g.get("resourceKey", {}).get("name") or "", name):
            return g["id"]
    raise SystemExit(f"group {name!r} not found — run the step-3 group instantiation first")


def group_member_ids(c, group_id: str) -> set[str]:
    body = c.get(f"/api/resources/groups/{group_id}/members", params={"_no_links": "true"}).json()
    return {r.get("identifier") for r in body.get("resourceList", [])}


def effective_policy(c, resource_id: str) -> str:
    r = c.post("/internal/policies/effective/query", json={"resourceIds": [resource_id]}).json()
    return r["effectivePolicies"][0]["policyId"]


def run_parity(ctx: Ctx, extra_vms: list[str]) -> int:
    """Effective-policy parity: every member of the posture's groups is governed by the policy that should.

    That is the posture policy for its VMs. For its hosts and clusters it is the posture policy too on an
    estate with no tier policies, and otherwise each object's tier policy: hardware takes its tier, so
    a host or cluster under its tier is correct, not shadowed, and one that no tier group holds is reported
    as untiered (it falls to the next policy that claims it; placement fit is reconcile_infra_groups.py
    --fit). Pure priority ordering is fragile (operators re-order), so THIS read-only check is the durable
    guarantee: it names any policy that wins where another should, so the order can be corrected deliberately.
    """
    names = {p["id"]: p["name"] for p in
             ctx.c.get("/api/policies", params={"_no_links": "true", "pageSize": 500}).json()["policySummaries"]}
    wtpc = next((pid for pid, nm in names.items() if same(nm, ctx.p.policy)), None)
    if not wtpc:
        raise SystemExit(f"{ctx.p.policy!r} not found")
    tier_model = any(is_tier_policy(nm) for nm in names.values())
    kind_of = {rid: "VM" for rid in extra_vms}
    for kind in ("VMs", "Hosts", "Clusters"):
        try:
            for rid in group_member_ids(ctx.c, resolve_group_id(ctx.c, posture_group(ctx.p.name, kind))):
                kind_of.setdefault(rid, kind[:-1])
        except SystemExit:
            pass
    tier_of: dict[str, str] = {}
    if tier_model:
        for g in list_groups(ctx.c, include_policy=True):
            if is_tier_group((g.get("resourceKey") or {}).get("name") or "") and g.get("policy"):
                for rid in group_member_ids(ctx.c, g["id"]):
                    tier_of.setdefault(rid, names.get(g["policy"], g["policy"]))
    expected = {rid: ctx.p.policy if (k == "VM" or not tier_model) else tier_of.get(rid) for rid, k in kind_of.items()}
    print(f"\nWTPC effective-policy parity · expected: {ctx.p.policy} for the posture's VMs"
          + ("; each host and cluster its tier's policy (hardware takes its tier)" if tier_model else " and its hardware"))
    if not kind_of:
        print("  no posture members resolved yet (untagged, or membership still re-resolving) — pass --representative to spot-check")
        return 0
    bad, untiered = [], []
    for rid in sorted(kind_of, key=lambda r: (kind_of[r], r)):
        pol, want = names.get(effective_policy(ctx.c, rid), "?"), expected[rid]
        if want is None:
            untiered.append(rid)
            mark = "⚠ UNTIERED (no tier group holds it)"
        elif same(pol, want):
            mark = "✅"
        else:
            bad.append((rid, pol, want))
            mark = f"❌ SHADOWED (expected {want})"
        print(f"  {kind_of[rid]:>7} {rid[:8]}: effective = {pol}  {mark}")
    if untiered:
        print(f"\n⚠ {len(untiered)} host or cluster member(s) sit in no tier group; run reconcile_infra_groups.py --fit")
    if bad:
        offenders = sorted({pol for _, pol, _ in bad})
        print(f"\n❌ {len(bad)}/{len(kind_of)} member(s) shadowed by: {offenders}")
        print("   FIX: in Administration ▸ Policies, rank the expected policy above the offender (priority order); "
              "the policy that should govern a member must outrank broad operator policies for it.")
        return 2
    print(f"\n✅ all {len(kind_of) - len(untiered)} governed member(s) resolve to the policy that should govern them — no precedence shadowing.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="WTPC effective-policy parity check (read-only)")
    ap.add_argument("--posture", default="prod-latency-critical-db",
                    help="posture name (its group names + policy name are derived)")
    ap.add_argument("--parity", action="store_true", help="(implied) run the read-only effective-policy parity check")
    ap.add_argument("--representative", help="optional VM id to include in the parity spot-check")
    ap.add_argument("--nonmember", help="optional VM id to include in the parity spot-check")
    args = ap.parse_args()
    with ops_client() as c:
        ctx = Ctx(c, execute=False, posture=Posture(args.posture))
        return run_parity(ctx, [v for v in (args.representative, args.nonmember) if v])


if __name__ == "__main__":
    sys.exit(main())
