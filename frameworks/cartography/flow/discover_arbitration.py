#!/usr/bin/env python3
"""Arbitration: fuse the lenses into one confidence-scored classification per VM (Phases 4-7, read-only).

No single lens is enough. Flows show who talks to whom but not what a thing is; a name shows intent
but lies when stale; a declared label is authoritative but only some workloads carry one. This is the
capstone: it runs the flow lens (shared services, boundaries + tiers) and the metadata lens
(environment + security zone) over one collection, then arbitrates them into a single verdict per VM,
with a confidence that reflects how many independent lenses agree and the conflicts that need a human.
The optional declared lens (the supervisor lens's export) is authoritative where present.

  python3 discover_arbitration.py                                   # 24h, print the classifications
  python3 discover_arbitration.py --hours 168 --declared recs.json  # fuse the supervisor lens
  python3 discover_arbitration.py --self-test                       # offline: reproduce the golden

Nothing is written. The review queue (conflicts + low confidence) is the actionable output: confirm
those, then the confident rows are safe to hand to the supervisor lens's write-back or your tagging.

Dependencies: Python 3 plus `pydantic`. One plane, from the environment (see lib/_client.py):
  export VRNI_HOST=<vrni-fqdn> VRNI_USERNAME=<user> VRNI_PASSWORD=<password>
  export VRNI_INSECURE=1     # only on a self-signed lab CA
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib._arbitrate import ArbitrationReport, SupervisorClassification, arbitrate, load_declared
from lib._boundaries import build_boundaries
from lib._env_zone import VmMetadata, build_env_zone_report, compute_internet_exposure
from lib._identity import VcfComponentInventory, build_inventory
from lib._shared_services import analyze, project_flows

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


def run_arbitration(raw_flows: list[dict], raw_vms: list[dict], *, hours: int, min_fan_in: int,
                    min_edge_weight: int, inventory: VcfComponentInventory | None = None,
                    declared: list[SupervisorClassification] | None = None) -> ArbitrationReport:
    """The whole pure pipeline: flows -> shared services (Phase 4) -> boundaries (Phase 5) -> env/zone
    (Phase 6) -> arbitrate (Phase 7). No I/O; the caller supplies the collected data."""
    projected = project_flows(raw_flows)
    shared = analyze(projected, total_flows=len(raw_flows), window_hours=hours,
                     min_fan_in=min_fan_in, component_inventory=inventory)
    quarantine = {c.destination for c in shared.quarantine}
    boundaries = build_boundaries(projected, shared_services=quarantine, total_flows=len(raw_flows),
                                  window_hours=hours, min_edge_weight=min_edge_weight)
    vms = [m for m in (VmMetadata.from_raw(r) for r in raw_vms) if m]
    env_zone = build_env_zone_report(vms, compute_internet_exposure(projected), window_hours=hours)
    return arbitrate(shared, boundaries, env_zone, supervisor=declared)


def render_summary(arb: ArbitrationReport) -> None:
    print(f"\n  Arbitration: {arb.total_vms} VMs classified over {arb.window_hours}h.")
    print(f"  roles       : {dict(sorted(arb.role_distribution.items()))}")
    print(f"  confidence  : {dict(sorted(arb.confidence_distribution.items()))}")
    print(f"  needs review: {arb.needs_review} (a conflict, or too few lenses to trust)\n")
    print(f"  REVIEW QUEUE (confirm these before any write-back): {len(arb.review_queue)}")
    for c in arb.review_queue:
        app = f" app={c.app_id}" if c.app_id else ""
        print(f"    {c.vm[:30]:30} {c.role:14} {c.confidence:7}{app} env={c.env} zone={c.zone}")
        for x in c.conflicts:
            print(f"        ! {x}")
    confident = [c for c in arb.classifications if not c.needs_review]
    print(f"\n  CONFIDENT ({len(confident)}, safe to hand to write-back):")
    for c in confident:
        lens = "+".join(c.lenses)
        app = f" app={c.app_id}({c.app_source})" if c.app_id else ""
        svc = f" {c.service_type}" if c.service_type else ""
        print(f"    {c.vm[:30]:30} {c.role:14} {c.confidence:7}{app}{svc} "
              f"env={c.env} zone={c.zone} [{lens}]")
    print("\n  Nothing was written. Confirm the review queue, then the confident rows are the input to "
          "the supervisor lens's write-back (../writeback_tags.py) or your own tagging.")


def self_test(*, update: bool = False) -> int:
    """Offline: run the full pipeline on the shipped fixture and compare to the golden report."""
    fx = json.loads((FIXTURES / "arbitration.json").read_text())
    declared = [SupervisorClassification(**d) for d in fx.get("declared", [])] or None
    inventory = build_inventory([tuple(r) for r in fx["identity"]]) if fx.get("identity") else None
    arb = run_arbitration(fx["flows"], fx["vms"], hours=fx["hours"], min_fan_in=fx["min_fan_in"],
                          min_edge_weight=fx.get("min_edge_weight", 1),
                          inventory=inventory, declared=declared)
    got = arb.model_dump(mode="json")
    golden = FIXTURES / "expected-arbitration.json"
    if update:
        golden.write_text(json.dumps(got, indent=2) + "\n")
        print(f"golden updated: {golden}")
        return 0
    if got == json.loads(golden.read_text()):
        print(f"self-test OK: the fixture ({len(fx['flows'])} flows, {len(fx['vms'])} VMs) reproduces "
              f"the golden arbitration exactly, {arb.total_vms} VMs classified, {arb.needs_review} in "
              f"the review queue, entirely offline.")
        return 0
    print("self-test FAILED: the arbitration output differs from the golden.")
    print("  (if the change is intended, re-run with --self-test --update to refresh the golden.)")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Arbitration: fuse the lenses into one scored classification")
    ap.add_argument("--hours", type=int, default=24, help="flow window length in hours (default 24)")
    ap.add_argument("--min-fan-in", type=int, default=5, help="shared-service fan-in threshold")
    ap.add_argument("--min-edge-weight", type=int, default=1, help="minimum flows for a VM-to-VM edge")
    ap.add_argument("--max-flows", type=int, default=5000, help="search cap (a hit is reported LOUD)")
    ap.add_argument("--declared", type=Path,
                    help="the supervisor lens's export (classify_supervisor.py --export): the declared lens")
    ap.add_argument("--no-identity", action="store_true", help="disable the vRNI entity-typing anchor")
    ap.add_argument("--export", type=Path, help="also write the full arbitration report as JSON here")
    ap.add_argument("--self-test", action="store_true", help="offline: reproduce the golden, then exit")
    ap.add_argument("--update", action="store_true", help="with --self-test: refresh the golden")
    args = ap.parse_args()

    if args.self_test:
        return self_test(update=args.update)

    from lib._client import vrni_client
    from lib._collect import collect_flows
    from lib._env_zone import collect_vm_details
    from lib._identity import collect_vcf_components

    declared = load_declared(args.declared) if args.declared else None
    with vrni_client() as client:
        raw_flows = collect_flows(client, hours=args.hours, max_flows=args.max_flows)
        raw_vms = collect_vm_details(client, hours=args.hours)
        inventory = None if args.no_identity else collect_vcf_components(client, hours=args.hours)
    if inventory is not None:
        print(f"  identity anchor: {inventory.total} VCF component(s) typed "
              f"{inventory.role_counts or {}}")

    arb = run_arbitration(raw_flows, raw_vms, hours=args.hours, min_fan_in=args.min_fan_in,
                          min_edge_weight=args.min_edge_weight, inventory=inventory, declared=declared)
    render_summary(arb)
    if args.export:
        args.export.write_text(json.dumps(arb.model_dump(mode="json"), indent=2) + "\n")
        print(f"\n  report written to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
