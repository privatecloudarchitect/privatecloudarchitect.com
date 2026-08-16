#!/usr/bin/env python3
"""WTPC effective-policy PARITY check (read-only) — every posture-group member's effective policy must BE
the WTPC posture policy. This is the gate apply.py runs per posture.

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
from lib._groups import list_groups


class Posture:
    """The posture identity the parity check needs: its name (→ group names) + its policy name."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.policy = f"PCA - WTPC - Policy - {name}"


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
        if g.get("resourceKey", {}).get("name") == name:
            return g["id"]
    raise SystemExit(f"group {name!r} not found — run the step-3 group instantiation first")


def group_member_ids(c, group_id: str) -> set[str]:
    body = c.get(f"/api/resources/groups/{group_id}/members", params={"_no_links": "true"}).json()
    return {r.get("identifier") for r in body.get("resourceList", [])}


def effective_policy(c, resource_id: str) -> str:
    r = c.post("/internal/policies/effective/query", json={"resourceIds": [resource_id]}).json()
    return r["effectivePolicies"][0]["policyId"]


def run_parity(ctx: Ctx, extra_vms: list[str]) -> int:
    """Effective-policy parity: every posture-group MEMBER's effective policy must BE the WTPC policy.

    Pure priority ordering is fragile (operators re-order; the priorities PUT has no GET to read current
    order safely), so THIS read-only check is the durable guarantee: it names the shadowing policy so the
    order can be corrected deliberately.
    """
    names = {p["id"]: p["name"] for p in
             ctx.c.get("/api/policies", params={"_no_links": "true", "pageSize": 500}).json()["policySummaries"]}
    wtpc = next((pid for pid, nm in names.items() if nm == ctx.p.policy), None)
    if not wtpc:
        raise SystemExit(f"{ctx.p.policy!r} not found")
    members = set(extra_vms)
    for kind in ("VMs", "Hosts", "Clusters"):
        try:
            members |= group_member_ids(ctx.c, resolve_group_id(ctx.c, f"PCA - WTPC - Group - {ctx.p.name} ({kind})"))
        except SystemExit:
            pass
    print(f"\nWTPC effective-policy parity · expected = {ctx.p.policy}")
    if not members:
        print("  no posture members resolved yet (untagged, or membership still re-resolving) — pass --representative to spot-check")
        return 0
    shadowed = [(rid, names.get(effective_policy(ctx.c, rid), "?")) for rid in sorted(members)]
    bad = [(rid, pol) for rid, pol in shadowed if pol != ctx.p.policy]
    for rid, pol in shadowed:
        ok = pol == ctx.p.policy
        print(f"  {rid[:8]}: effective = {pol}  {'✅' if ok else '❌ SHADOWED'}")
    if bad:
        offenders = sorted({pol for _, pol in bad})
        print(f"\n❌ {len(bad)}/{len(shadowed)} member(s) shadowed by: {offenders}")
        print("   FIX: raise the WTPC policy above these in Administration ▸ Policies (priority order) — "
              "the posture policy must outrank broad operator policies for its members.")
        return 2
    print(f"\n✅ all {len(shadowed)} member(s) resolve to the WTPC policy — no precedence shadowing.")
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
