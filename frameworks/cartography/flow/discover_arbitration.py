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
  python3 discover_arbitration.py --hours 168 --declared recs.json \
      --confirmations confirmed.txt --export-recommendations handoff.json --record arbitration.json
  python3 discover_arbitration.py --self-test                       # offline: reproduce the goldens

Nothing is written on the estate. The review queue (conflicts + low confidence) is the actionable output:
work it into a confirmations file, one decision per line (`<vm> accept`, or `<vm> <app|tier|env|zone>
<value>`), and the same file keeps those rows resolved on every later run. `--export-recommendations` then
writes the rows that need no review in the supervisor lens's recommendations schema, approve only where a
person or the workload's own label set the value, for `../writeback_tags.py --recommendations` (dry-run
first). `--record` writes the run in counts and the framework's vocabulary, refusing any name or address.

Dependencies: Python 3 plus `pydantic`. One plane, from the environment (see lib/_client.py):
  ( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vrni-password )   # paste the password, then Ctrl-D
  export VRNI_HOST=<vrni-fqdn> VRNI_USERNAME=<user> VRNI_PASSWORD_FILE=~/.vcf/vrni-password
  export VRNI_INSECURE=1     # only on a self-signed lab CA
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from lib._arbitrate import (ArbitrationReport, SupervisorClassification, apply_confirmations, arbitrate,
                            conflict_kind, load_confirmations, load_declared, parse_confirmations,
                            to_recommendations)
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


def counts_record(arb: ArbitrationReport, *, cap_hit: bool, inventory: VcfComponentInventory | None,
                  declared_vms: int, applied: int, stale: int, handoff: dict | None) -> dict:
    """The run in counts and the framework's vocabulary: the window, the roles and confidence spread, how often
    each lens placed a workload, the review queue by conflict kind, the identity anchor's typed components, the
    confirmations folded in, and the hand-off's size. No workload, application id or address enters it."""
    return {
        "window_hours": arb.window_hours, "search_cap_hit": cap_hit, "total_vms": arb.total_vms,
        "identity": None if inventory is None else {"typed": inventory.total,
                                                    "roles": dict(sorted(inventory.role_counts.items()))},
        "roles": dict(sorted(arb.role_distribution.items())),
        "confidence": dict(sorted(arb.confidence_distribution.items())),
        "lenses": dict(sorted(Counter(lens for c in arb.classifications for lens in c.lenses).items())),
        "needs_review": arb.needs_review,
        "conflicts": dict(sorted(Counter(conflict_kind(x) for c in arb.classifications for x in c.conflicts).items())),
        "declared_vms": declared_vms,
        "confirmations": {"applied": applied, "stale": stale},
        "handoff": None if handoff is None else {
            k: handoff[k] for k in ("tag_ready_vms", "held_for_review", "address_only", "recommended_count",
                                    "confirm_count", "category_distribution")},
    }


def write_record(path: Path, record: dict, arb: ArbitrationReport) -> None:
    """Write the counts-only record, refusing one in which any workload, application id or address survived."""
    import re
    import time
    text = json.dumps({"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **record}, indent=1)
    names = {c.vm for c in arb.classifications} | {c.app_id for c in arb.classifications if c.app_id}
    leaked = [n for n in names if n and re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w.-])", text)]
    assert not leaked and not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text), \
        "a name or an address reached the record; nothing was written"
    path.write_text(text + "\n", encoding="utf-8")
    print(f"  record written to {path} (counts only)")


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
    print("\n  Nothing was written. Work the review queue into a confirmations file (--confirmations), then "
          "hand the confident rows to the write-back: --export-recommendations, then ../writeback_tags.py "
          "--recommendations <file> --approve-file <file> (dry-run first).")


def self_test(*, update: bool = False) -> int:
    """Offline: run the full pipeline on the shipped fixture and compare to the golden report; then fold in the
    fixture's confirmations and compare the hand-off to its golden."""
    fx = json.loads((FIXTURES / "arbitration.json").read_text())
    declared = [SupervisorClassification(**d) for d in fx.get("declared", [])] or None
    inventory = build_inventory([tuple(r) for r in fx["identity"]]) if fx.get("identity") else None
    arb = run_arbitration(fx["flows"], fx["vms"], hours=fx["hours"], min_fan_in=fx["min_fan_in"],
                          min_edge_weight=fx.get("min_edge_weight", 1),
                          inventory=inventory, declared=declared)
    got = arb.model_dump(mode="json")
    confirmations = parse_confirmations(fx.get("confirmations", []))
    confirmed, stale = apply_confirmations(arb, confirmations)
    handoff = to_recommendations(confirmed)
    golden, golden_handoff = FIXTURES / "expected-arbitration.json", FIXTURES / "expected-handoff.json"
    if update:
        golden.write_text(json.dumps(got, indent=2) + "\n")
        golden_handoff.write_text(json.dumps(handoff, indent=2) + "\n")
        print(f"goldens updated: {golden.name}, {golden_handoff.name}")
        return 0
    if got == json.loads(golden.read_text()) and handoff == json.loads(golden_handoff.read_text()):
        print(f"self-test OK: the fixture ({len(fx['flows'])} flows, {len(fx['vms'])} VM records) reproduces "
              f"the golden arbitration exactly, {arb.total_vms} workloads classified, {arb.needs_review} in "
              f"the review queue; with {len(confirmations)} confirmations ({len(stale)} for a workload not seen), "
              f"the hand-off carries {len(handoff['recommendations'])} rows, {handoff['recommended_count']} approve "
              f"and {handoff['confirm_count']} confirm, entirely offline.")
        return 0
    print("self-test FAILED: the arbitration or the hand-off differs from its golden.")
    print("  (if the change is intended, re-run with --self-test --update to refresh the goldens.)")
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
    ap.add_argument("--confirmations", type=Path,
                    help="a person's decisions, one per line: '<vm> accept' or '<vm> <app|tier|env|zone> <value>'")
    ap.add_argument("--export-recommendations", type=Path,
                    help="write the rows that need no review as the write-back's recommendations file")
    ap.add_argument("--record", type=Path, help="write a counts-only record of the run (no name or address)")
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
    confirmations = load_confirmations(args.confirmations) if args.confirmations else []
    with vrni_client() as client:
        raw_flows = collect_flows(client, hours=args.hours, max_flows=args.max_flows)
        raw_vms = collect_vm_details(client, hours=args.hours)
        inventory = None if args.no_identity else collect_vcf_components(client, hours=args.hours)
    if inventory is not None:
        print(f"  identity anchor: {inventory.total} VCF component(s) typed "
              f"{inventory.role_counts or {}}")

    arb = run_arbitration(raw_flows, raw_vms, hours=args.hours, min_fan_in=args.min_fan_in,
                          min_edge_weight=args.min_edge_weight, inventory=inventory, declared=declared)
    arb, stale = apply_confirmations(arb, confirmations)
    if confirmations:
        print(f"  confirmations: {len(confirmations)} read, {len(stale)} for a workload not seen in this window")
    render_summary(arb)
    if args.export:
        args.export.write_text(json.dumps(arb.model_dump(mode="json"), indent=2) + "\n")
        print(f"\n  report written to {args.export}")
    handoff = to_recommendations(arb) if args.export_recommendations or args.record else None
    if args.export_recommendations:
        args.export_recommendations.write_text(json.dumps(handoff, indent=2) + "\n")
        print(f"  hand-off written to {args.export_recommendations}: {len(handoff['recommendations'])} rows, "
              f"{handoff['recommended_count']} approve, {handoff['confirm_count']} confirm; "
              f"{handoff['held_for_review']} workloads held for review")
    if args.record:
        write_record(args.record, counts_record(
            arb, cap_hit=len(raw_flows) >= args.max_flows, inventory=inventory,
            declared_vms=len(declared or []), applied=len(confirmations) - sum(1 for c in confirmations if c.vm in stale),
            stale=len(stale), handoff=handoff), arb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
